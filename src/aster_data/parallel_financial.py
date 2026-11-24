"""Low-concurrency PIT financial backfill alongside the main market pipeline.

The worker discovers instruments from membership snapshot checkpoints and
writes to the same PIT artifact directory used by ``full_download``.  The main
pipeline therefore treats these files as completed checkpoints later.  This
controller has a separate lock, status, failure file, and log so it never
overwrites the market pipeline's operational state.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
from filelock import FileLock, Timeout

from .full_download import (
    _artifact_is_complete,
    _atomic_json,
    _financial_worker,
    _now,
    _run_child,
    _symbol_to_qlib,
)


LOGGER = logging.getLogger("aster_data.parallel_financial")


def discover_instruments(snapshot_dir: Path) -> list[str]:
    instruments: set[str] = set()
    for path in sorted(snapshot_dir.glob("snapshot_requested_*.csv")):
        try:
            frame = pd.read_csv(path, usecols=["instrument"])
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            LOGGER.warning("skip unreadable snapshot %s: %s", path, exc)
            continue
        instruments.update(
            frame["instrument"].dropna().astype(str).str.upper().tolist()
        )
    return sorted(instruments)


class ParallelFinancialBackfill:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project_root = Path(args.project_root).resolve()
        self.raw_root = self.project_root / "data" / "raw" / "qlib_full"
        self.snapshot_dir = self.raw_root / "csi500_snapshots"
        self.pit_root = self.raw_root / "pit"
        self.run_root = self.project_root / "run" / "parallel_financial"
        self.status_path = self.run_root / "status.json"
        self.failure_path = self.run_root / "failures.json"
        self.main_status_path = self.project_root / "run" / "full_download" / "status.json"
        self.failures = self._load_failures()

    def _load_failures(self) -> dict[str, dict[str, str]]:
        if not self.failure_path.exists():
            return {}
        try:
            return json.loads(self.failure_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _main_stage(self) -> str:
        try:
            payload = json.loads(self.main_status_path.read_text(encoding="utf-8"))
            return str(payload.get("stage") or "unknown")
        except (OSError, json.JSONDecodeError):
            return "unknown"

    def _status(self, state: str = "running", **progress) -> None:
        _atomic_json(
            self.status_path,
            {
                "pid": os.getpid(),
                "state": state,
                "stage": "financial",
                "start": self.args.start,
                "end": self.args.end,
                "updated_at": _now(),
                "main_pipeline_stage": self._main_stage(),
                **progress,
            },
        )

    def run(self) -> None:
        processed_this_run: set[str] = set()
        while True:
            main_stage = self._main_stage()
            if main_stage in {"financial", "complete"}:
                self._status(
                    state="handed_off",
                    reason=f"main pipeline reached {main_stage}",
                    processed_this_run=len(processed_this_run),
                    failures=len(self.failures),
                )
                LOGGER.info("main pipeline reached %s; stopping parallel backfill", main_stage)
                return

            instruments = discover_instruments(self.snapshot_dir)
            completed = sum(self._is_complete(instrument) for instrument in instruments)
            self._status(
                total_discovered=len(instruments),
                completed=completed,
                failures=len(self.failures),
            )
            pending = [
                instrument
                for instrument in instruments
                if instrument not in processed_this_run and not self._is_complete(instrument)
            ]
            if not pending:
                if main_stage != "membership":
                    self._status(
                        state="complete",
                        total_discovered=len(instruments),
                        completed=completed,
                        failures=len(self.failures),
                    )
                    LOGGER.info("financial backfill complete for %s instruments", len(instruments))
                    return
                LOGGER.info("no pending discovered instruments; waiting for more membership snapshots")
                time.sleep(self.args.rescan_seconds)
                processed_this_run.clear()
                continue

            for instrument in pending:
                if self._main_stage() in {"financial", "complete"}:
                    break
                success = False
                message = "not attempted"
                symbol = _symbol_to_qlib(instrument)
                for attempt in range(1, self.args.retries + 1):
                    success, message = _run_child(
                        _financial_worker,
                        (
                            str(self.project_root),
                            str(self.raw_root),
                            symbol,
                            self.args.start,
                            self.args.end,
                        ),
                        self.args.timeout,
                    )
                    if success and self._is_complete(instrument):
                        break
                    LOGGER.warning(
                        "financial %s attempt %s/%s failed: %s",
                        instrument,
                        attempt,
                        self.args.retries,
                        message,
                    )
                    time.sleep(min(30, attempt * 5))

                processed_this_run.add(instrument)
                if success and self._is_complete(instrument):
                    self.failures.pop(instrument, None)
                    completed += 1
                else:
                    self.failures[instrument] = {"error": message, "updated_at": _now()}
                _atomic_json(self.failure_path, self.failures)
                self._status(
                    total_discovered=len(instruments),
                    completed=completed,
                    current=instrument,
                    current_success=success,
                    failures=len(self.failures),
                )
                LOGGER.info(
                    "financial progress %s/%s current=%s success=%s failures=%s",
                    completed,
                    len(instruments),
                    instrument,
                    success,
                    len(self.failures),
                )
                time.sleep(self.args.request_delay)

    def _is_complete(self, instrument: str) -> bool:
        symbol = _symbol_to_qlib(instrument)
        target = self.pit_root / f"{symbol}_{self.args.start}_{self.args.end}.csv"
        return _artifact_is_complete(target, self.args.start, self.args.end)


def _setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.5)
    parser.add_argument("--rescan-seconds", type=int, default=30)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve()
    run_root = project_root / "run" / "parallel_financial"
    _setup_logging(project_root / "logs" / "parallel_financial.log")
    run_root.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(run_root / "pipeline.lock"))
    try:
        with lock.acquire(timeout=0):
            ParallelFinancialBackfill(args).run()
    except Timeout:
        LOGGER.error("another parallel financial backfill already holds %s", lock.lock_file)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
