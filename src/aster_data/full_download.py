"""Resumable full CSI500 market and PIT financial data download.

Stage order is deliberately strict:

1. Weekly CSI500 historical membership snapshots.
2. Daily bars for the union of all constituents observed in those snapshots.
3. PIT financial fields for the same union.

Each symbol is executed in a child process.  This gives the controller a hard
timeout for upstream calls that otherwise may block indefinitely on Windows.
Existing artifacts with matching metadata are checkpoints and are skipped on
restart.
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd
from filelock import FileLock, Timeout

from .qlib_collectors import QlibCollectorAdapter


LOGGER = logging.getLogger("aster_data.full_download")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.2 * (attempt + 1))


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)


def _artifact_is_complete(data_path: Path, start: str, end: str) -> bool:
    metadata_path = data_path.with_suffix(".metadata.json")
    if not data_path.exists() or not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        metadata.get("requested_start") == start
        and metadata.get("requested_end") == end
        and int(metadata.get("row_count", -1)) >= 0
    )


def _symbol_to_yahoo(instrument: str) -> str:
    instrument = instrument.upper()
    if instrument.startswith("SH"):
        return f"{instrument[2:]}.SS"
    if instrument.startswith("SZ"):
        return f"{instrument[2:]}.SZ"
    raise ValueError(f"Unsupported CSI500 instrument: {instrument}")


def _symbol_to_qlib(instrument: str) -> str:
    instrument = instrument.upper()
    if instrument.startswith("SH"):
        return f"{instrument[2:]}.ss"
    if instrument.startswith("SZ"):
        return f"{instrument[2:]}.sz"
    raise ValueError(f"Unsupported CSI500 instrument: {instrument}")


def _market_worker(project_root: str, raw_root: str, symbol: str, start: str, end: str) -> None:
    adapter = QlibCollectorAdapter(Path(project_root))
    adapter.raw_root = Path(raw_root)
    adapter.collect_yahoo_daily(symbol, start, end)


def _financial_worker(project_root: str, raw_root: str, symbol: str, start: str, end: str) -> None:
    adapter = QlibCollectorAdapter(Path(project_root))
    adapter.raw_root = Path(raw_root)
    adapter.collect_pit_symbol(symbol, start, end)


def _run_child(
    target: Callable[..., None],
    args: tuple,
    timeout_seconds: int,
) -> tuple[bool, str]:
    context = mp.get_context("spawn")
    process = context.Process(target=target, args=args)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join(5)
        return False, f"timeout after {timeout_seconds}s"
    if process.exitcode != 0:
        return False, f"worker exit code {process.exitcode}"
    return True, "ok"


class FullDownloadPipeline:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project_root = Path(args.project_root).resolve()
        self.raw_root = self.project_root / "data" / "raw" / "qlib_full"
        self.run_root = self.project_root / "run" / "full_download"
        self.status_path = self.run_root / "status.json"
        self.failure_path = self.run_root / "failures.json"
        self.log_path = self.project_root / "logs" / "full_download.log"
        self.adapter = QlibCollectorAdapter(self.project_root)
        self.adapter.raw_root = self.raw_root
        self.failures: dict[str, dict] = self._load_failures()

    def _load_failures(self) -> dict[str, dict]:
        if not self.failure_path.exists():
            return {"membership": {}, "market": {}, "financial": {}}
        try:
            payload = json.loads(self.failure_path.read_text(encoding="utf-8"))
            payload.setdefault("membership", {})
            payload.setdefault("market", {})
            payload.setdefault("financial", {})
            return payload
        except (OSError, json.JSONDecodeError):
            return {"membership": {}, "market": {}, "financial": {}}

    def _save_failures(self) -> None:
        _atomic_json(self.failure_path, self.failures)

    def _status(self, stage: str, state: str = "running", **progress) -> None:
        payload = {
            "pid": os.getpid(),
            "state": state,
            "stage": stage,
            "start": self.args.start,
            "end": self.args.end,
            "updated_at": _now(),
            "log_path": str(self.log_path),
            **progress,
        }
        _atomic_json(self.status_path, payload)

    def run(self) -> None:
        LOGGER.info(
            "pipeline start pid=%s range=%s..%s project=%s",
            os.getpid(),
            self.args.start,
            self.args.end,
            self.project_root,
        )
        self._status("membership")
        instruments = self.collect_membership()
        LOGGER.info("membership complete: %s distinct historical constituents", len(instruments))

        self._status("market", total=len(instruments), completed=0)
        self.collect_market(instruments)
        LOGGER.info("market stage complete; starting financial stage")

        self._status("financial", total=len(instruments), completed=0)
        self.collect_financial(instruments)

        self._status(
            "complete",
            state="complete",
            instruments=len(instruments),
            membership_warnings=len(self.failures["membership"]),
            market_failures=len(self.failures["market"]),
            financial_failures=len(self.failures["financial"]),
        )
        LOGGER.info(
            "pipeline complete: instruments=%s membership_warnings=%s "
            "market_failures=%s financial_failures=%s",
            len(instruments),
            len(self.failures["membership"]),
            len(self.failures["market"]),
            len(self.failures["financial"]),
        )

    def collect_membership(self) -> list[str]:
        from data_collector.cn_index.collector import CSI500Index

        snapshot_dir = self.raw_root / "csi500_snapshots"
        start_ts = pd.Timestamp(self.args.start).normalize()
        end_ts = pd.Timestamp(self.args.end).normalize()
        requested_dates = list(pd.date_range(start_ts, end_ts, freq=f"{self.args.snapshot_step_days}D"))
        if not requested_dates or requested_dates[-1] != end_ts:
            requested_dates.append(end_ts)

        LOGGER.info("membership snapshots planned=%s", len(requested_dates))
        import baostock as bs

        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {login.error_code} {login.error_msg}")
        try:
            for index, requested in enumerate(requested_dates, start=1):
                target = snapshot_dir / f"snapshot_requested_{requested:%Y-%m-%d}.csv"
                if target.exists() and target.with_suffix(".metadata.json").exists():
                    self._status(
                        "membership",
                        total=len(requested_dates),
                        completed=index,
                        cached=True,
                        warnings=len(self.failures["membership"]),
                    )
                    continue

                last_error = "unknown"
                for attempt in range(1, self.args.retries + 1):
                    try:
                        frame = CSI500Index.get_data_from_baostock(requested.date())
                        if frame is None or frame.empty:
                            raise RuntimeError("source returned an empty snapshot")
                        frame = frame.rename(columns={"date": "snapshot_date", "symbol": "instrument"})
                        frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"])
                        if frame["snapshot_date"].max() > requested:
                            raise RuntimeError("source snapshot is after requested date")
                        observed_rows = len(frame)
                        quality = "ok" if observed_rows == 500 else "row_count_mismatch"
                        requested_key = requested.strftime("%Y-%m-%d")
                        if observed_rows != 500:
                            warning = {
                                "quality": quality,
                                "expected_rows": 500,
                                "observed_rows": observed_rows,
                                "updated_at": _now(),
                            }
                            self.failures["membership"][requested_key] = warning
                            self._save_failures()
                            LOGGER.warning(
                                "membership %s retained with quality warning: "
                                "expected 500 rows, received %s",
                                requested.date(), observed_rows,
                            )
                        else:
                            if self.failures["membership"].pop(requested_key, None) is not None:
                                self._save_failures()
                        frame.insert(0, "requested_as_of", requested)
                        frame["source"] = "qlib_v0.9.7_baostock_query_zz500_stocks"
                        self.adapter._write_artifact(frame, target, {
                            "dataset": "csi500_membership_snapshot",
                            "requested_as_of": requested.strftime("%Y-%m-%d"),
                            "requested_start": self.args.start,
                            "requested_end": self.args.end,
                            "source_snapshot_dates": sorted(
                                frame["snapshot_date"].dt.strftime("%Y-%m-%d").unique()
                            ),
                            "expected_row_count": 500,
                            "observed_row_count": observed_rows,
                            "quality": quality,
                        })
                        last_error = ""
                        break
                    except Exception as error:  # noqa: BLE001 - preserve upstream failure
                        last_error = repr(error)
                        LOGGER.warning(
                            "membership %s attempt %s/%s failed: %s",
                            requested.date(), attempt, self.args.retries, last_error,
                        )
                        time.sleep(min(30, attempt * 3))
                if last_error:
                    requested_key = requested.strftime("%Y-%m-%d")
                    self.failures["membership"][requested_key] = {
                        "quality": "unavailable_after_retries",
                        "error": last_error,
                        "updated_at": _now(),
                    }
                    self._save_failures()
                    LOGGER.error(
                        "membership snapshot unavailable for %s after retries; "
                        "recording the gap and continuing",
                        requested.date(),
                    )

                self._status(
                    "membership",
                    total=len(requested_dates),
                    completed=index,
                    cached=False,
                    warnings=len(self.failures["membership"]),
                )
                if index == 1 or index % 25 == 0:
                    LOGGER.info("membership progress %s/%s", index, len(requested_dates))
                time.sleep(self.args.snapshot_delay)
        finally:
            bs.logout()

        snapshot_files = sorted(snapshot_dir.glob("snapshot_requested_*.csv"))
        frames = [pd.read_csv(path, usecols=["requested_as_of", "snapshot_date", "instrument"]) for path in snapshot_files]
        history = pd.concat(frames, ignore_index=True).drop_duplicates()
        history = history.sort_values(["requested_as_of", "instrument"]).reset_index(drop=True)
        self.adapter._write_artifact(
            history,
            self.raw_root / "csi500_membership_weekly.csv",
            {
                "dataset": "csi500_membership_weekly_candidate",
                "requested_start": self.args.start,
                "requested_end": self.args.end,
                "snapshot_count": len(snapshot_files),
                "quality": "weekly_candidate_requires_official_CSI_effective_date_correction",
            },
        )

        instruments = sorted(history["instrument"].dropna().astype(str).str.upper().unique())
        union = pd.DataFrame({"instrument": instruments})
        union["yahoo_symbol"] = union["instrument"].map(_symbol_to_yahoo)
        union["qlib_symbol"] = union["instrument"].map(_symbol_to_qlib)
        self.adapter._write_artifact(
            union,
            self.raw_root / "csi500_historical_union.csv",
            {
                "dataset": "csi500_historical_constituent_union",
                "requested_start": self.args.start,
                "requested_end": self.args.end,
            },
        )
        return instruments

    def collect_market(self, instruments: Iterable[str]) -> None:
        instruments = list(instruments)
        market_root = self.raw_root / "yahoo_daily"
        completed = 0
        for instrument in instruments:
            symbol = _symbol_to_yahoo(instrument)
            safe_symbol = symbol.lower().replace(".", "_")
            target = market_root / f"{safe_symbol}_{self.args.start}_{self.args.end}.csv"
            if _artifact_is_complete(target, self.args.start, self.args.end):
                completed += 1
                self.failures["market"].pop(instrument, None)
                self._status("market", total=len(instruments), completed=completed, current=instrument, cached=True)
                continue

            success = False
            message = "not attempted"
            for attempt in range(1, self.args.retries + 1):
                success, message = _run_child(
                    _market_worker,
                    (str(self.project_root), str(self.raw_root), symbol, self.args.start, self.args.end),
                    self.args.market_timeout,
                )
                if success and _artifact_is_complete(target, self.args.start, self.args.end):
                    break
                LOGGER.warning(
                    "market %s attempt %s/%s failed: %s",
                    instrument, attempt, self.args.retries, message,
                )
                time.sleep(min(60, attempt * 5))

            completed += 1
            if success and target.exists():
                self.failures["market"].pop(instrument, None)
            else:
                self.failures["market"][instrument] = {"error": message, "updated_at": _now()}
            self._save_failures()
            self._status(
                "market",
                total=len(instruments),
                completed=completed,
                current=instrument,
                failures=len(self.failures["market"]),
            )
            LOGGER.info(
                "market progress %s/%s current=%s success=%s failures=%s",
                completed, len(instruments), instrument, success, len(self.failures["market"]),
            )

    def collect_financial(self, instruments: Iterable[str]) -> None:
        instruments = list(instruments)
        financial_root = self.raw_root / "pit"
        completed = 0
        for instrument in instruments:
            symbol = _symbol_to_qlib(instrument)
            target = financial_root / f"{symbol}_{self.args.start}_{self.args.end}.csv"
            if _artifact_is_complete(target, self.args.start, self.args.end):
                completed += 1
                self.failures["financial"].pop(instrument, None)
                self._status("financial", total=len(instruments), completed=completed, current=instrument, cached=True)
                continue

            success = False
            message = "not attempted"
            for attempt in range(1, self.args.retries + 1):
                success, message = _run_child(
                    _financial_worker,
                    (str(self.project_root), str(self.raw_root), symbol, self.args.start, self.args.end),
                    self.args.financial_timeout,
                )
                if success and _artifact_is_complete(target, self.args.start, self.args.end):
                    break
                LOGGER.warning(
                    "financial %s attempt %s/%s failed: %s",
                    instrument, attempt, self.args.retries, message,
                )
                time.sleep(min(60, attempt * 5))

            completed += 1
            if success and target.exists():
                self.failures["financial"].pop(instrument, None)
            else:
                self.failures["financial"][instrument] = {"error": message, "updated_at": _now()}
            self._save_failures()
            self._status(
                "financial",
                total=len(instruments),
                completed=completed,
                current=instrument,
                failures=len(self.failures["financial"]),
            )
            LOGGER.info(
                "financial progress %s/%s current=%s success=%s failures=%s",
                completed, len(instruments), instrument, success, len(self.failures["financial"]),
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[2]
    today = pd.Timestamp.now().normalize()
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument("--start", default=(today - pd.DateOffset(years=10)).strftime("%Y-%m-%d"))
    parser.add_argument("--end", default=today.strftime("%Y-%m-%d"))
    parser.add_argument("--snapshot-step-days", type=int, default=7)
    parser.add_argument("--snapshot-delay", type=float, default=0.2)
    parser.add_argument("--market-timeout", type=int, default=300)
    parser.add_argument("--financial-timeout", type=int, default=900)
    parser.add_argument("--retries", type=int, default=3)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve()
    log_path = project_root / "logs" / "full_download.log"
    _setup_logging(log_path)

    lock_path = project_root / "run" / "full_download" / "pipeline.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path))
    try:
        with lock.acquire(timeout=0):
            pipeline = FullDownloadPipeline(args)
            try:
                pipeline.run()
            except Exception as error:  # noqa: BLE001 - background status must retain traceback
                LOGGER.exception("pipeline failed: %s", error)
                pipeline._status("failed", state="failed", error=repr(error), traceback=traceback.format_exc())
                raise
    except Timeout:
        LOGGER.error("another full download pipeline already holds %s", lock_path)
        raise SystemExit(3)


if __name__ == "__main__":
    mp.freeze_support()
    main()

