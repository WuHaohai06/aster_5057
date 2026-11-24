"""Resumable low-concurrency downloader for multi-dimensional factor inputs.

The downloader deliberately processes one dataset for the full historical
CSI500 universe before moving to the next dataset.  This makes the relatively
cheap daily valuation data available before the slower financial statements.
All financial observations retain their public notice date for PIT joins.
"""

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

from .io import instrument_from_code, numeric_code, sha256_file, write_json_atomic


LOGGER = logging.getLogger("aster_data.factor_input_download")
STAGES = ("valuation", "balance", "profit", "cashflow", "industry")
VALUATION_COLUMNS = {
    "数据日期": "date",
    "当日收盘价": "close",
    "当日涨跌幅": "pct_change",
    "总市值": "total_market_cap",
    "流通市值": "float_market_cap",
    "总股本": "total_shares",
    "流通股本": "float_shares",
    "PE(TTM)": "pe_ttm",
    "PE(静)": "pe_static",
    "市净率": "pb",
    "PEG值": "peg",
    "市现率": "pcf",
    "市销率": "ps",
}
INDUSTRY_COLUMNS = {
    "机构名称": "company_name",
    "证券代码": "security_code",
    "新证券简称": "security_name",
    "变更日期": "change_date",
    "分类标准编码": "classification_code",
    "分类标准": "classification_standard",
    "行业编码": "industry_code",
    "行业门类": "industry_section",
    "行业次类": "industry_subclass",
    "行业大类": "industry_division",
    "行业中类": "industry_group",
}


def _now() -> str:
    return datetime.now(tz=ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def discover_instruments(interval_path: Path) -> list[str]:
    frame = pd.read_parquet(interval_path, columns=["instrument"])
    return sorted(
        {instrument_from_code(value) for value in frame["instrument"].dropna().astype(str)}
    )


def normalize_valuation(
    frame: pd.DataFrame, *, instrument: str, start: str, end: str
) -> pd.DataFrame:
    missing = set(VALUATION_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"valuation fields missing: {sorted(missing)}")
    result = frame.rename(columns=VALUATION_COLUMNS)[list(VALUATION_COLUMNS.values())].copy()
    result.insert(0, "instrument", instrument_from_code(instrument))
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.loc[result["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    numeric = [column for column in result.columns if column not in {"instrument", "date"}]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="coerce")
    result["available_at"] = result["date"]
    return result.sort_values("date").drop_duplicates(["instrument", "date"], keep="last")


def normalize_statement(
    frame: pd.DataFrame, *, instrument: str, start: str, end: str
) -> pd.DataFrame:
    required = {"REPORT_DATE", "NOTICE_DATE"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"financial statement fields missing: {sorted(missing)}")
    result = frame.copy()
    result.insert(0, "instrument", instrument_from_code(instrument))
    result["REPORT_DATE"] = pd.to_datetime(result["REPORT_DATE"], errors="coerce")
    result["NOTICE_DATE"] = pd.to_datetime(result["NOTICE_DATE"], errors="coerce")
    if "UPDATE_DATE" in result.columns:
        result["UPDATE_DATE"] = pd.to_datetime(result["UPDATE_DATE"], errors="coerce")
    history_start = pd.Timestamp(start) - pd.DateOffset(years=2)
    result = result.loc[
        result["REPORT_DATE"].ge(history_start)
        & result["NOTICE_DATE"].notna()
        & result["NOTICE_DATE"].le(pd.Timestamp(end))
    ].copy()
    result["report_date"] = result["REPORT_DATE"]
    result["available_at"] = result["NOTICE_DATE"]
    return result.sort_values(["available_at", "report_date"]).drop_duplicates(
        ["instrument", "report_date", "available_at"], keep="last"
    )


def normalize_industry(frame: pd.DataFrame, *, instrument: str) -> pd.DataFrame:
    result = frame.rename(columns=INDUSTRY_COLUMNS).copy()
    for column in ("classification_standard", "industry_code"):
        if column not in result.columns:
            result[column] = pd.Series(dtype="string")
    if "change_date" not in result.columns:
        result["change_date"] = pd.Series(dtype="datetime64[ns]")
    result.insert(0, "instrument", instrument_from_code(instrument))
    result["change_date"] = pd.to_datetime(result["change_date"], errors="coerce")
    result["available_at"] = result["change_date"]
    return result.sort_values("available_at").drop_duplicates(
        ["instrument", "available_at", "classification_standard"], keep="last"
    )


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


class FactorInputDownloader:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project_root = Path(args.project_root).resolve()
        self.output_root = self.project_root / "data" / "raw" / "factor_inputs"
        self.run_root = self.project_root / "run" / "factor_input_download"
        self.status_path = self.run_root / "status.json"
        self.failure_path = self.run_root / "failures.json"
        self.interval_path = (
            self.project_root / "data" / "curated" / "csi500_universe" / "intervals.parquet"
        )
        self.stages = tuple(args.stages)
        self.failures = self._read_json(self.failure_path, {})

    @staticmethod
    def _read_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _paths(self, stage: str, instrument: str) -> tuple[Path, Path]:
        target = self.output_root / stage / f"{instrument}.parquet"
        return target, target.with_suffix(".metadata.json")

    def _complete(self, stage: str, instrument: str) -> bool:
        target, metadata = self._paths(stage, instrument)
        if not target.exists() or not metadata.exists():
            return False
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            return (
                payload.get("stage") == stage
                and payload.get("instrument") == instrument
                and payload.get("requested_start") == self.args.start
                and payload.get("requested_end") == self.args.end
                and payload.get("sha256") == sha256_file(target)
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def _status(self, state: str, **values) -> None:
        write_json_atomic(
            self.status_path,
            {
                "pid": os.getpid(),
                "state": state,
                "start": self.args.start,
                "end": self.args.end,
                "stages": list(self.stages),
                "updated_at": _now(),
                **values,
            },
        )

    def _fetch(self, stage: str, instrument: str) -> pd.DataFrame:
        import akshare as ak

        code = numeric_code(instrument)
        if stage == "valuation":
            return normalize_valuation(
                ak.stock_value_em(symbol=code),
                instrument=instrument,
                start=self.args.start,
                end=self.args.end,
            )
        em_symbol = instrument_from_code(instrument)
        if stage == "balance":
            return normalize_statement(
                ak.stock_balance_sheet_by_report_em(symbol=em_symbol),
                instrument=instrument,
                start=self.args.start,
                end=self.args.end,
            )
        if stage == "profit":
            return normalize_statement(
                ak.stock_profit_sheet_by_report_em(symbol=em_symbol),
                instrument=instrument,
                start=self.args.start,
                end=self.args.end,
            )
        if stage == "cashflow":
            return normalize_statement(
                ak.stock_cash_flow_sheet_by_report_em(symbol=em_symbol),
                instrument=instrument,
                start=self.args.start,
                end=self.args.end,
            )
        if stage == "industry":
            return normalize_industry(
                ak.stock_industry_change_cninfo(
                    symbol=code,
                    start_date=self.args.start.replace("-", ""),
                    end_date=self.args.end.replace("-", ""),
                ),
                instrument=instrument,
            )
        raise ValueError(f"unsupported stage: {stage}")

    @staticmethod
    def _is_rate_limit(error: Exception) -> bool:
        text = f"{type(error).__name__}: {error}".lower()
        return any(token in text for token in ("ratelimit", "rate limit", "限流", "频繁"))

    def _collect_one(self, stage: str, instrument: str) -> int:
        frame = self._fetch(stage, instrument)
        target, metadata = self._paths(stage, instrument)
        _write_parquet_atomic(target, frame)
        write_json_atomic(
            metadata,
            {
                "dataset": "aster-factor-inputs-v1",
                "stage": stage,
                "instrument": instrument,
                "requested_start": self.args.start,
                "requested_end": self.args.end,
                "rows": len(frame),
                "columns": list(frame.columns),
                "available_at_semantics": (
                    "public notice date" if stage in {"balance", "profit", "cashflow"}
                    else "observation/change date"
                ),
                "source": "AKShare 1.20.65 (Eastmoney/CNInfo)",
                "retrieved_at": _now(),
                "sha256": sha256_file(target),
            },
        )
        return len(frame)

    def run(self) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)
        instruments = discover_instruments(self.interval_path)
        completed_artifacts = sum(
            self._complete(stage, instrument)
            for stage in self.stages
            for instrument in instruments
        )
        total_artifacts = len(instruments) * len(self.stages)
        self._status(
            "running",
            stage=self.stages[0],
            instruments=len(instruments),
            total_artifacts=total_artifacts,
            completed_artifacts=completed_artifacts,
            failures=len(self.failures),
        )
        for stage_index, stage in enumerate(self.stages, start=1):
            stage_completed = sum(self._complete(stage, item) for item in instruments)
            for instrument_index, instrument in enumerate(instruments, start=1):
                if self._complete(stage, instrument):
                    continue
                success = False
                error_text = "not attempted"
                rows = 0
                for attempt in range(1, self.args.retries + 1):
                    try:
                        rows = self._collect_one(stage, instrument)
                        success = True
                        break
                    except Exception as error:  # upstream errors must not stop the backfill
                        error_text = f"{type(error).__name__}: {error}"
                        LOGGER.warning(
                            "%s %s attempt %s/%s failed: %s",
                            stage,
                            instrument,
                            attempt,
                            self.args.retries,
                            error_text,
                        )
                        if self._is_rate_limit(error):
                            self._status(
                                "rate_limited",
                                stage=stage,
                                stage_index=stage_index,
                                instruments=len(instruments),
                                current=instrument,
                                instrument_index=instrument_index,
                                completed_artifacts=completed_artifacts,
                                total_artifacts=total_artifacts,
                                failures=len(self.failures),
                                retry_after_seconds=self.args.rate_limit_delay,
                            )
                            time.sleep(self.args.rate_limit_delay)
                        else:
                            time.sleep(min(60.0, self.args.retry_delay * attempt))
                key = f"{stage}:{instrument}"
                if success:
                    self.failures.pop(key, None)
                    completed_artifacts += 1
                    stage_completed += 1
                else:
                    self.failures[key] = {"error": error_text, "updated_at": _now()}
                write_json_atomic(self.failure_path, self.failures)
                self._status(
                    "running",
                    stage=stage,
                    stage_index=stage_index,
                    instruments=len(instruments),
                    current=instrument,
                    instrument_index=instrument_index,
                    current_success=success,
                    current_rows=rows,
                    stage_completed=stage_completed,
                    completed_artifacts=completed_artifacts,
                    total_artifacts=total_artifacts,
                    failures=len(self.failures),
                )
                LOGGER.info(
                    "%s progress %s/%s current=%s success=%s rows=%s all=%s/%s",
                    stage,
                    stage_completed,
                    len(instruments),
                    instrument,
                    success,
                    rows,
                    completed_artifacts,
                    total_artifacts,
                )
                time.sleep(self.args.request_delay)
        self._status(
            "complete",
            stage="complete",
            instruments=len(instruments),
            completed_artifacts=completed_artifacts,
            total_artifacts=total_artifacts,
            failures=len(self.failures),
        )


def _setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    for handler in (logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument("--start", default="2016-11-24")
    parser.add_argument("--end", default="2026-11-24")
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=2.0)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument("--rate-limit-delay", type=float, default=300.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve()
    run_root = project_root / "run" / "factor_input_download"
    run_root.mkdir(parents=True, exist_ok=True)
    _setup_logging(project_root / "logs" / "factor_input_download.log")
    lock = FileLock(str(run_root / "pipeline.lock"))
    try:
        with lock.acquire(timeout=0):
            FactorInputDownloader(args).run()
    except Timeout:
        LOGGER.error("another factor input downloader already holds %s", lock.lock_file)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
