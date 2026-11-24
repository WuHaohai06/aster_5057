"""Official CFFEX IC archives and a lagged, auditable continuous return series."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from filelock import FileLock, Timeout

from .io import sha256_file, write_bytes_atomic, write_json_atomic


IC_PATTERN = re.compile(r"^IC\d{4}$")


def _now() -> str:
    return pd.Timestamp.now(tz=ZoneInfo("Asia/Shanghai")).isoformat()


def archive_url(month: str, *, scheme: str = "http") -> str:
    return f"{scheme}://www.cffex.com.cn/sj/historysj/{month}/zip/{month}.zip"


def fetch_month_archive(
    month: str, archive_root: Path, *, retries: int = 4, timeout: int = 60
) -> tuple[Path, dict]:
    target = archive_root / f"{month}.zip"
    if target.exists():
        try:
            with zipfile.ZipFile(target) as handle:
                if handle.testzip() is not None:
                    raise zipfile.BadZipFile("archive CRC check failed")
            return target, {
                "month": month,
                "source": archive_url(month),
                "sha256": sha256_file(target),
                "cached": True,
            }
        except zipfile.BadZipFile:
            target.unlink()
    archive_root.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        for scheme in ("https", "http"):
            url = archive_url(month, scheme=scheme)
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.get(url, timeout=(10, timeout))
                response.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(response.content)) as handle:
                    if handle.testzip() is not None:
                        raise zipfile.BadZipFile("archive CRC check failed")
                write_bytes_atomic(target, response.content)
                return target, {
                    "month": month,
                    "source": url,
                    "sha256": sha256_file(target),
                    "cached": False,
                }
            except (requests.RequestException, zipfile.BadZipFile) as error:
                last_error = error
        time.sleep(min(15, attempt * 2))
    raise RuntimeError(f"CFFEX archive {month} failed: {last_error}")


def parse_ic_archive(path: Path) -> pd.DataFrame:
    rows: list[dict] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            base = Path(name).name
            if not re.fullmatch(r"\d{8}_1\.csv", base):
                continue
            date = pd.Timestamp(base[:8])
            raw = archive.read(name)
            frame = None
            for encoding in ("gb18030", "utf-8-sig"):
                try:
                    frame = pd.read_csv(io.BytesIO(raw), encoding=encoding, dtype=str)
                    break
                except UnicodeDecodeError:
                    continue
            if frame is None or frame.shape[1] < 11:
                raise ValueError(f"unexpected CFFEX layout in {path.name}:{name}")
            frame.columns = [str(column).strip() for column in frame.columns]
            symbols = frame.iloc[:, 0].astype(str).str.strip().str.upper()
            selected = frame.loc[symbols.str.fullmatch(IC_PATTERN, na=False)].copy()
            for index, item in selected.iterrows():
                values = item.tolist()
                rows.append(
                    {
                        "date": date,
                        "contract": symbols.loc[index],
                        "open": values[1],
                        "high": values[2],
                        "low": values[3],
                        "volume": values[4],
                        "turnover": values[5],
                        "open_interest": values[6],
                        "close": values[8],
                        "settle": values[9],
                        "pre_settle": values[10],
                        "source_archive": path.name,
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    numeric = [
        "open",
        "high",
        "low",
        "volume",
        "turnover",
        "open_interest",
        "close",
        "settle",
        "pre_settle",
    ]
    result[numeric] = result[numeric].apply(
        lambda column: pd.to_numeric(
            column.astype(str).str.replace(",", "", regex=False), errors="coerce"
        )
    )
    result = result.dropna(subset=["close", "contract", "date"])
    result = result.sort_values(["date", "contract"]).drop_duplicates(
        ["date", "contract"], keep="last"
    )
    return result.reset_index(drop=True)


def _expiry_period(contract: str) -> pd.Period:
    year = 2000 + int(contract[2:4])
    month = int(contract[4:6])
    return pd.Period(f"{year:04d}-{month:02d}", freq="M")


def build_lagged_continuous(
    contracts: pd.DataFrame, *, multiplier: float, margin_rate: float
) -> pd.DataFrame:
    if contracts.empty:
        raise ValueError("IC contract history is empty")
    data = contracts.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data["expiry"] = data["contract"].map(_expiry_period)
    data = data.loc[data["expiry"] >= data["date"].dt.to_period("M")].copy()
    selections: dict[pd.Timestamp, str] = {}
    groups = {date: group.set_index("contract") for date, group in data.groupby("date")}
    for date, group in groups.items():
        ranked = group.sort_values(
            ["open_interest", "volume", "contract"],
            ascending=[False, False, True],
            na_position="last",
        )
        selections[pd.Timestamp(date)] = str(ranked.index[0])
    dates = sorted(groups)
    rows = []
    active = selections[dates[0]]
    previous_date: pd.Timestamp | None = None
    for date in dates:
        day = groups[date]
        forced_roll = active not in day.index
        if forced_roll:
            active = selections[date]
        item = day.loc[active]
        hedge_return = 0.0
        return_basis = "initial"
        if previous_date is not None:
            previous = groups[previous_date]
            if active in previous.index and pd.notna(previous.loc[active, "close"]):
                hedge_return = float(item["close"] / previous.loc[active, "close"] - 1.0)
                return_basis = "same_contract_close"
            elif pd.notna(item["pre_settle"]) and float(item["pre_settle"]) > 0:
                hedge_return = float(item["close"] / item["pre_settle"] - 1.0)
                return_basis = "exchange_pre_settle_fallback"
            else:
                raise ValueError(f"cannot build IC return for {date.date()} {active}")
        next_contract = selections[date]
        roll = bool(next_contract != active)
        closing_price = float(day.loc[next_contract, "close"])
        rows.append(
            {
                "date": date,
                "contract": active,
                "close": float(item["close"]),
                "settle": float(item["settle"]) if pd.notna(item["settle"]) else None,
                "hedge_return": hedge_return,
                "return_basis": return_basis,
                "roll": roll,
                "forced_roll": forced_roll,
                "next_contract": next_contract,
                "closing_price": closing_price,
                "multiplier": multiplier,
                "margin_rate_assumption": margin_rate,
            }
        )
        active = next_contract
        previous_date = date
    result = pd.DataFrame(rows)
    if result["hedge_return"].abs().max() > 0.25:
        raise ValueError("IC continuous series contains an implausible daily return")
    result["nav_index"] = (1.0 + result["hedge_return"]).cumprod()
    return result


def collect_ic_history(
    *,
    start: str,
    end: str,
    archive_root: Path,
    output_root: Path,
    multiplier: float = 200.0,
    margin_rate: float = 0.12,
    max_workers: int = 2,
    allow_missing_months: bool = False,
    status_path: Path | None = None,
) -> dict:
    periods = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    sources: list[dict] = []
    failures: dict[str, str] = {}
    archive_paths: list[Path] = []
    if status_path is not None:
        write_json_atomic(
            status_path,
            {
                "pid": os.getpid(),
                "state": "running",
                "stage": "download_archives",
                "total": len(periods),
                "completed": 0,
                "failures": 0,
                "updated_at": _now(),
            },
        )
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        jobs = {
            executor.submit(fetch_month_archive, period.strftime("%Y%m"), archive_root): period
            for period in periods
        }
        for future in as_completed(jobs):
            key = jobs[future].strftime("%Y%m")
            try:
                path, source = future.result()
                archive_paths.append(path)
                sources.append(source)
            except Exception as error:
                failures[key] = f"{type(error).__name__}: {error}"
            if status_path is not None:
                write_json_atomic(
                    status_path,
                    {
                        "pid": os.getpid(),
                        "state": "running",
                        "stage": "download_archives",
                        "total": len(periods),
                        "completed": len(archive_paths) + len(failures),
                        "failures": len(failures),
                        "current": key,
                        "updated_at": _now(),
                    },
                )
    if failures and not allow_missing_months:
        write_json_atomic(output_root / "failures.json", failures)
        raise RuntimeError(f"missing {len(failures)} CFFEX monthly archives")
    frames = [parse_ic_archive(path) for path in sorted(archive_paths)]
    contracts = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
    contracts["date"] = pd.to_datetime(contracts["date"])
    contracts = contracts.loc[
        contracts["date"].between(pd.Timestamp(start), pd.Timestamp(end))
    ].sort_values(["date", "contract"])
    continuous = build_lagged_continuous(
        contracts, multiplier=multiplier, margin_rate=margin_rate
    )
    output_root.mkdir(parents=True, exist_ok=True)
    contract_path = output_root / "contracts.parquet"
    daily_path = output_root / "continuous.parquet"
    for frame, target in ((contracts, contract_path), (continuous, daily_path)):
        temporary = target.with_name(target.name + ".tmp")
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, target)
    payload = {
        "dataset": "cffex_ic_daily_v1",
        "source": "CFFEX official monthly historical archives",
        "start": start,
        "end": end,
        "contract_rows": len(contracts),
        "sessions": len(continuous),
        "rolls": int(continuous["roll"].sum()),
        "multiplier": multiplier,
        "margin_rate_assumption": margin_rate,
        "selection_rule": "highest open interest then volume; selected at t for position t+1",
        "missing_months": failures,
        "archives": sorted(sources, key=lambda item: item["month"]),
        "files": {
            contract_path.name: sha256_file(contract_path),
            daily_path.name: sha256_file(daily_path),
        },
    }
    write_json_atomic(output_root / "manifest.json", payload)
    if status_path is not None:
        write_json_atomic(
            status_path,
            {
                "pid": os.getpid(),
                "state": "complete",
                "stage": "ic_futures",
                "total": len(periods),
                "completed": len(archive_paths) + len(failures),
                "failures": len(failures),
                "sessions": len(continuous),
                "rolls": int(continuous["roll"].sum()),
                "updated_at": _now(),
            },
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--multiplier", type=float, default=200.0)
    parser.add_argument("--margin-rate", type=float, default=0.12)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--allow-missing-months", action="store_true")
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--lock-path", type=Path)
    args = parser.parse_args()
    kwargs = dict(
        start=args.start,
        end=args.end,
        archive_root=args.archive_root,
        output_root=args.output_root,
        multiplier=args.multiplier,
        margin_rate=args.margin_rate,
        max_workers=args.max_workers,
        allow_missing_months=args.allow_missing_months,
        status_path=args.status_path,
    )
    if args.lock_path is None:
        result = collect_ic_history(**kwargs)
    else:
        args.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(args.lock_path))
        try:
            with lock.acquire(timeout=0):
                result = collect_ic_history(**kwargs)
        except Timeout:
            raise SystemExit(f"another IC collector holds {args.lock_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
