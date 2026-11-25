"""Resumable AKShare/EM adjusted A-share daily-bar collector."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from filelock import FileLock, Timeout

from .io import instrument_from_code, numeric_code, sha256_file, write_bytes_atomic, write_json_atomic


LOGGER = logging.getLogger("aster_data.akshare_market")
SOURCE = "akshare_1.20.65_stock_zh_a_hist_em"
SINA_SOURCE = "akshare_1.20.65_stock_zh_a_hist_sina"
FIELD_MAP = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude_pct",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover_pct",
}


def _now() -> str:
    return datetime.now(tz=ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def normalize_akshare_daily(
    frame: pd.DataFrame, *, instrument: str, adjustment: str
) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("AKShare returned an empty daily frame")
    unknown = set(FIELD_MAP).difference(frame.columns)
    if unknown:
        raise ValueError(f"AKShare daily fields are missing: {sorted(unknown)}")
    result = frame.rename(columns=FIELD_MAP)[list(FIELD_MAP.values())].copy()
    result.insert(0, "instrument", instrument_from_code(instrument))
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.strftime("%Y-%m-%d")
    numeric = [column for column in result.columns if column not in {"instrument", "date"}]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="coerce")
    result = result.dropna(subset=["open", "high", "low", "close"])
    result = result.sort_values("date").drop_duplicates("date", keep="last")
    if result.empty or not result["date"].is_monotonic_increasing:
        raise ValueError("AKShare daily frame has no valid ordered rows")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("AKShare daily frame contains non-positive prices")
    result["adjustment"] = adjustment or "none"
    result["source"] = SOURCE
    return result.reset_index(drop=True)


def normalize_sina_daily(
    frame: pd.DataFrame, *, instrument: str, adjustment: str
) -> pd.DataFrame:
    """Map AKShare's Sina fallback to the canonical Eastmoney-shaped contract."""
    required = {"date", "open", "high", "low", "close", "volume", "amount"}
    missing = required.difference(frame.columns)
    if frame.empty:
        raise ValueError("AKShare Sina fallback returned an empty daily frame")
    if missing:
        raise ValueError(f"AKShare Sina fields are missing: {sorted(missing)}")
    result = frame[list(required)].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise")
    numeric = ["open", "high", "low", "close", "volume", "amount"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="coerce")
    result = result.dropna(subset=["open", "high", "low", "close"])
    result = result.sort_values("date").drop_duplicates("date", keep="last")
    if result.empty or (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("AKShare Sina fallback has no valid positive-price rows")
    previous_close = result["close"].shift(1)
    result["amplitude_pct"] = (result["high"] - result["low"]) / previous_close * 100.0
    result["pct_change"] = result["close"].pct_change(fill_method=None) * 100.0
    result["change"] = result["close"] - previous_close
    if "turnover" in frame.columns:
        turnover = pd.to_numeric(frame.loc[result.index, "turnover"], errors="coerce")
        result["turnover_pct"] = turnover * 100.0
    else:
        result["turnover_pct"] = pd.NA
    # Eastmoney reports volume in 100-share lots; Sina reports shares.
    result["volume"] = result["volume"] / 100.0
    result.insert(0, "instrument", instrument_from_code(instrument))
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    result["adjustment"] = adjustment or "none"
    result["source"] = SINA_SOURCE
    columns = [
        "instrument", "date", "open", "close", "high", "low", "volume", "amount",
        "amplitude_pct", "pct_change", "change", "turnover_pct", "adjustment", "source",
    ]
    return result[columns].reset_index(drop=True)


class AkshareMarketCollector:
    def __init__(self, project_root: Path, *, adjustment: str = "hfq", timeout: int = 30):
        self.project_root = project_root.resolve()
        self.adjustment = adjustment
        self.timeout = timeout
        self.output_root = self.project_root / "data" / "raw" / "akshare_daily"
        self.run_root = self.project_root / "run" / "akshare_market"

    def collect_one(self, instrument: str, start: str, end: str) -> Path:
        import akshare as ak

        target, metadata = self._artifact_paths(instrument, start, end)
        if self._complete(target, metadata, start, end):
            return target
        normalized = instrument_from_code(instrument)
        if hasattr(ak, "set_timeout"):
            ak.set_timeout(self.timeout)
        source = SOURCE
        price_semantics = "Eastmoney adjusted OHLC as returned by AKShare"
        try:
            frame = ak.stock_zh_a_hist_em(
                symbol=numeric_code(normalized),
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust=self.adjustment,
            )
            result = normalize_akshare_daily(
                frame, instrument=normalized, adjustment=self.adjustment
            )
        except Exception as primary_error:
            LOGGER.warning(
                "%s Eastmoney request failed; trying Sina fallback: %s",
                normalized,
                primary_error,
            )
            frame = ak.stock_zh_a_hist_sina(
                symbol=normalized.lower(),
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust=self.adjustment,
            )
            result = normalize_sina_daily(
                frame, instrument=normalized, adjustment=self.adjustment
            )
            source = SINA_SOURCE
            price_semantics = "Sina adjusted OHLC fallback as returned by AKShare"
        csv_bytes = result.to_csv(index=False, lineterminator="\n").encode("utf-8")
        write_bytes_atomic(target, csv_bytes)
        write_json_atomic(
            metadata,
            {
                "dataset": "stock_daily_primary_candidate",
                "instrument": normalized,
                "requested_start": start,
                "requested_end": end,
                "adjustment": self.adjustment or "none",
                "price_semantics": price_semantics,
                "row_count": len(result),
                "first_date": result["date"].iloc[0],
                "last_date": result["date"].iloc[-1],
                "source": source,
                "sha256": sha256_file(target),
                "retrieved_at": _now(),
            },
        )
        return target

    def _artifact_paths(self, instrument: str, start: str, end: str) -> tuple[Path, Path]:
        normalized = instrument_from_code(instrument)
        target = self.output_root / f"{normalized}_{start}_{end}_{self.adjustment or 'none'}.csv"
        return target, target.with_suffix(".metadata.json")

    @staticmethod
    def _complete(target: Path, metadata: Path, start: str, end: str) -> bool:
        if not target.exists() or not metadata.exists():
            return False
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            return (
                payload.get("requested_start") == start
                and payload.get("requested_end") == end
                and int(payload.get("row_count", 0)) > 0
                and payload.get("sha256") == sha256_file(target)
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def run(
        self,
        instruments: list[str],
        *,
        start: str,
        end: str,
        retries: int,
        request_delay: float,
        rate_limit_delay: float,
    ) -> None:
        failures_path = self.run_root / "failures.json"
        status_path = self.run_root / "status.json"
        try:
            failures = json.loads(failures_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures = {}
        completed = 0
        for instrument in instruments:
            target, metadata = self._artifact_paths(instrument, start, end)
            cached = self._complete(target, metadata, start, end)
            success = cached
            error = "not attempted"
            for attempt in range(1, retries + 1) if not cached else ():
                try:
                    self.collect_one(instrument, start, end)
                    success = True
                    break
                except Exception as exc:  # preserve upstream failures and continue
                    error = f"{type(exc).__name__}: {exc}"
                    rate_limited = "ratelimit" in type(exc).__name__.lower() or "限流" in str(exc)
                    LOGGER.warning(
                        "%s attempt %s/%s failed: %s", instrument, attempt, retries, error
                    )
                    if rate_limited:
                        write_json_atomic(
                            status_path,
                            {
                                "pid": os.getpid(),
                                "state": "rate_limited",
                                "stage": "akshare_market",
                                "start": start,
                                "end": end,
                                "adjustment": self.adjustment or "none",
                                "total": len(instruments),
                                "completed": completed,
                                "current": instrument,
                                "failures": len(failures),
                                "retry_after_seconds": rate_limit_delay,
                                "updated_at": _now(),
                            },
                        )
                        LOGGER.warning("AKShare rate limit; sleeping %.0f seconds", rate_limit_delay)
                        time.sleep(rate_limit_delay)
                    else:
                        time.sleep(min(30.0, 3.0 * attempt))
            completed += 1
            if success:
                failures.pop(instrument, None)
            else:
                failures[instrument] = {"error": error, "updated_at": _now()}
            write_json_atomic(failures_path, failures)
            write_json_atomic(
                status_path,
                {
                    "pid": os.getpid(),
                    "state": "running",
                    "stage": "akshare_market",
                    "start": start,
                    "end": end,
                    "adjustment": self.adjustment or "none",
                    "total": len(instruments),
                    "completed": completed,
                    "current": instrument,
                    "current_success": success,
                    "failures": len(failures),
                    "updated_at": _now(),
                },
            )
            LOGGER.info(
                "AKShare market progress %s/%s current=%s success=%s failures=%s",
                completed,
                len(instruments),
                instrument,
                success,
                len(failures),
            )
            if not cached:
                time.sleep(request_delay)
        write_json_atomic(
            status_path,
            {
                "pid": os.getpid(),
                "state": "complete",
                "stage": "akshare_market",
                "start": start,
                "end": end,
                "adjustment": self.adjustment or "none",
                "total": len(instruments),
                "completed": completed,
                "failures": len(failures),
                "updated_at": _now(),
            },
        )


def _setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--instruments", type=Path)
    parser.add_argument("--adjust", choices=["", "qfq", "hfq"], default="hfq")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.5)
    parser.add_argument("--rate-limit-delay", type=float, default=300.0)
    parser.add_argument("--limit", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = args.project_root.resolve()
    instrument_path = args.instruments or (
        project_root / "data" / "raw" / "qlib_full" / "csi500_historical_union.csv"
    )
    frame = pd.read_csv(instrument_path, dtype=str)
    if "instrument" not in frame:
        raise ValueError(f"instrument column is missing from {instrument_path}")
    instruments = sorted({instrument_from_code(value) for value in frame["instrument"].dropna()})
    if args.limit is not None:
        instruments = instruments[: args.limit]
    collector = AkshareMarketCollector(
        project_root, adjustment=args.adjust, timeout=args.timeout
    )
    collector.run(
        instruments,
        start=args.start,
        end=args.end,
        retries=args.retries,
        request_delay=args.request_delay,
        rate_limit_delay=args.rate_limit_delay,
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    run_root = root / "run" / "akshare_market"
    run_root.mkdir(parents=True, exist_ok=True)
    _setup_logging(root / "logs" / "akshare_market.log")
    lock = FileLock(str(run_root / "pipeline.lock"))
    try:
        with lock.acquire(timeout=0):
            main()
    except Timeout:
        LOGGER.error("another AKShare market collector holds %s", lock.lock_file)
        raise SystemExit(3)
