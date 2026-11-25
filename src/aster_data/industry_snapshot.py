"""Build a static, explicitly non-PIT industry snapshot for course demos."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .io import instrument_from_code, sha256_file, write_json_atomic


CNINFO_URL = "https://webapi.cninfo.com.cn/api/stock/p_stock2110"
FIELD_MAP = {
    "ORGNAME": "company_name",
    "SECCODE": "security_code",
    "SECNAME": "security_name",
    "VARYDATE": "change_date",
    "F001V": "classification_code",
    "F002V": "classification_standard",
    "F003V": "industry_code",
    "F004V": "industry_section",
    "F005V": "industry_subclass",
    "F006V": "industry_division",
    "F007V": "industry_group",
    "F008C": "latest_record_flag",
}
PREFERRED_STANDARDS = ("008001", "008014", "008019", "008003")


def _now() -> str:
    return datetime.now(tz=ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _cninfo_key() -> str:
    import py_mini_racer
    from akshare.stock.finance.stock_industry_cninfo import _get_file_content_ths

    runtime = py_mini_racer.MiniRacer()
    runtime.eval(_get_file_content_ths("cninfo.js"))
    return str(runtime.call("getResCode1"))


def _headers(key: str) -> dict[str, str]:
    return {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Enckey": key,
        "Origin": "https://webapi.cninfo.com.cn",
        "Referer": "https://webapi.cninfo.com.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }


def fetch_history(
    *, code: str, start: str, end: str, key: str, timeout: float = 30.0
) -> list[dict]:
    params = {
        "scode": code,
        "sdate": pd.Timestamp(start).strftime("%Y-%m-%d"),
        "edate": pd.Timestamp(end).strftime("%Y-%m-%d"),
    }
    response = requests.post(
        CNINFO_URL, params=params, headers=_headers(key), timeout=timeout
    )
    response.raise_for_status()
    payload = json.loads(response.content.decode("utf-8"))
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise ValueError("CNInfo industry response has no records list")
    return [
        {FIELD_MAP.get(name, name): value for name, value in record.items()}
        for record in records
    ]


def _select_latest(instrument: str, records: list[dict], snapshot_date: str) -> dict:
    frame = pd.DataFrame(records)
    if frame.empty:
        return {
            "instrument": instrument,
            "industry_code": "UNKNOWN",
            "industry_name": "Unknown",
            "classification_code": "",
            "classification_standard": "",
            "change_date": pd.NaT,
            "snapshot_date": pd.Timestamp(snapshot_date),
            "source": "CNInfo p_stock2110",
        }
    frame["change_date"] = pd.to_datetime(frame.get("change_date"), errors="coerce")
    frame = frame.loc[frame["change_date"].le(pd.Timestamp(snapshot_date))].copy()
    if frame.empty:
        return _select_latest(instrument, [], snapshot_date)
    selected = None
    classification_codes = (
        frame["classification_code"].astype(str)
        if "classification_code" in frame
        else pd.Series("", index=frame.index, dtype="string")
    )
    for standard in PREFERRED_STANDARDS:
        candidate = frame.loc[classification_codes.eq(standard)]
        if not candidate.empty:
            selected = candidate.sort_values("change_date").iloc[-1]
            break
    if selected is None:
        selected = frame.sort_values("change_date").iloc[-1]
    labels = [
        selected.get("industry_division"),
        selected.get("industry_group"),
        selected.get("industry_subclass"),
        selected.get("industry_section"),
    ]
    industry_name = next(
        (str(value).strip() for value in labels if pd.notna(value) and str(value).strip()),
        "Unknown",
    )
    return {
        "instrument": instrument,
        "industry_code": str(selected.get("industry_code") or "UNKNOWN"),
        "industry_name": industry_name,
        "industry_section": str(selected.get("industry_section") or ""),
        "industry_division": str(selected.get("industry_division") or ""),
        "industry_group": str(selected.get("industry_group") or ""),
        "classification_code": str(selected.get("classification_code") or ""),
        "classification_standard": str(selected.get("classification_standard") or ""),
        "change_date": selected.get("change_date"),
        "snapshot_date": pd.Timestamp(snapshot_date),
        "source": "CNInfo p_stock2110",
    }


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def _build_benchmark_weights(
    *, market_path: Path, valuation_root: Path, mapping: pd.DataFrame,
    start: str, end: str,
) -> pd.DataFrame:
    market = pd.read_parquet(
        market_path, columns=["date", "instrument", "csi500_member"]
    )
    market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    members = market.loc[
        market["date"].between(pd.Timestamp(start), pd.Timestamp(end))
        & market["csi500_member"].astype(bool),
        ["date", "instrument"],
    ].drop_duplicates()
    wanted = set(members["instrument"])
    frames = []
    for path in valuation_root.glob("*.parquet"):
        instrument = instrument_from_code(path.stem)
        if instrument not in wanted:
            continue
        frame = pd.read_parquet(path, columns=["date", "instrument", "float_market_cap"])
        frames.append(frame)
    if not frames:
        raise ValueError("no valuation files overlap the industry snapshot universe")
    valuation = pd.concat(frames, ignore_index=True)
    valuation["date"] = pd.to_datetime(valuation["date"]).dt.normalize()
    joined = members.merge(valuation, on=["date", "instrument"], how="left")
    joined = joined.merge(mapping[["instrument", "industry_name"]], on="instrument", how="left")
    joined["industry_name"] = joined["industry_name"].fillna("Unknown")
    joined["float_market_cap"] = pd.to_numeric(
        joined["float_market_cap"], errors="coerce"
    )
    valid_cap = joined["float_market_cap"].gt(0.0)
    joined["raw_weight"] = joined["float_market_cap"].where(valid_cap, 1.0)
    totals = joined.groupby("date")["raw_weight"].transform("sum")
    joined["member_weight"] = joined["raw_weight"].div(totals)
    result = (
        joined.groupby(["date", "industry_name"], as_index=False)
        .agg(
            benchmark_weight=("member_weight", "sum"),
            member_count=("instrument", "nunique"),
            float_market_cap=("float_market_cap", "sum"),
        )
        .sort_values(["date", "industry_name"])
    )
    return result


def build_snapshot(
    *, project_root: Path, start: str, end: str, snapshot_date: str,
    workers: int = 6, retries: int = 3,
) -> dict:
    project_root = project_root.resolve()
    market_path = project_root / "data/curated/market/daily.parquet"
    valuation_root = project_root / "data/raw/factor_inputs/valuation"
    raw_root = project_root / "data/raw/industry_snapshot"
    output_root = project_root / "data/curated/industry_snapshot"
    run_root = project_root / "run/industry_snapshot"
    raw_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    market = pd.read_parquet(
        market_path, columns=["date", "instrument", "csi500_member"]
    )
    market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    instruments = sorted(
        market.loc[
            market["date"].between(pd.Timestamp(start), pd.Timestamp(end))
            & market["csi500_member"].astype(bool),
            "instrument",
        ].unique()
    )
    key = _cninfo_key()
    failures: dict[str, str] = {}

    def collect(instrument: str) -> tuple[str, list[dict]]:
        path = raw_root / f"{instrument}.json"
        if path.exists():
            return instrument, json.loads(path.read_text(encoding="utf-8")).get("records", [])
        error = None
        for attempt in range(1, retries + 1):
            try:
                records = fetch_history(
                    code=instrument[2:], start="1990-01-01", end=snapshot_date, key=key
                )
                write_json_atomic(
                    path,
                    {
                        "instrument": instrument,
                        "snapshot_date": snapshot_date,
                        "retrieved_at": _now(),
                        "records": records,
                    },
                )
                return instrument, records
            except Exception as exc:  # upstream failures are retained and retried
                error = f"{type(exc).__name__}: {exc}"
                time.sleep(min(10.0, attempt * 1.5))
        raise RuntimeError(error or "industry fetch failed")

    completed: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(collect, instrument): instrument for instrument in instruments}
        for index, future in enumerate(as_completed(futures), start=1):
            instrument = futures[future]
            try:
                name, records = future.result()
                completed[name] = records
            except Exception as exc:
                failures[instrument] = f"{type(exc).__name__}: {exc}"
            write_json_atomic(
                run_root / "status.json",
                {
                    "state": "running",
                    "snapshot_date": snapshot_date,
                    "completed": index,
                    "successful": len(completed),
                    "failures": len(failures),
                    "total": len(instruments),
                    "updated_at": _now(),
                },
            )

    rows = [
        _select_latest(instrument, completed.get(instrument, []), snapshot_date)
        for instrument in instruments
    ]
    mapping = pd.DataFrame(rows).sort_values("instrument")
    snapshot_path = output_root / "latest.parquet"
    _write_parquet_atomic(snapshot_path, mapping)
    benchmark = _build_benchmark_weights(
        market_path=market_path,
        valuation_root=valuation_root,
        mapping=mapping,
        start=start,
        end=end,
    )
    benchmark_path = output_root / "benchmark_weights.parquet"
    _write_parquet_atomic(benchmark_path, benchmark)
    known = mapping["industry_name"].ne("Unknown")
    manifest = {
        "dataset": "aster-static-industry-snapshot-v1",
        "snapshot_date": snapshot_date,
        "start": start,
        "end": end,
        "instruments": len(mapping),
        "classified": int(known.sum()),
        "coverage": float(known.mean()),
        "industries": int(mapping.loc[known, "industry_name"].nunique()),
        "failures": failures,
        "industry_mapping_mode": "static_snapshot",
        "pit_compliant": False,
        "uses_future_information": True,
        "source": "CNInfo p_stock2110 via UTF-8 raw JSON",
        "files": {
            "latest.parquet": sha256_file(snapshot_path),
            "benchmark_weights.parquet": sha256_file(benchmark_path),
        },
        "generated_at": _now(),
    }
    write_json_atomic(output_root / "manifest.json", manifest)
    write_json_atomic(run_root / "failures.json", failures)
    write_json_atomic(
        run_root / "status.json",
        {"state": "complete", **manifest, "updated_at": _now()},
    )
    return manifest

