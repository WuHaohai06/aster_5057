"""Version-locked adapters for Qlib's public data collectors.

Qlib's collector scripts are not part of the installed ``pyqlib`` wheel and
their ``main`` branch can be incompatible with a stable wheel.  This adapter
loads the vendored v0.9.7 scripts and exposes narrowly scoped collection
functions with explicit source metadata and point-in-time boundary checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

import pandas as pd


EXPECTED_QLIB_VERSION = "0.9.7"


@dataclass(frozen=True)
class CollectedArtifact:
    data_path: Path
    metadata_path: Path
    row_count: int
    sha256: str


class QlibCollectorAdapter:
    """Run selected Qlib collectors without their full-market wrappers."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.vendor_root = self.project_root / "vendor" / "qlib-v0.9.7"
        self.raw_root = self.project_root / "data" / "raw" / "qlib_collector"
        self._prepare_imports()
        self._validate_version()

    def _prepare_imports(self) -> None:
        scripts = self.vendor_root / "scripts"
        yahoo_scripts = scripts / "data_collector" / "yahoo"
        if not scripts.exists():
            raise FileNotFoundError(f"Missing vendored Qlib collectors: {scripts}")
        for path in (str(yahoo_scripts), str(scripts)):
            if path not in sys.path:
                sys.path.insert(0, path)

    @staticmethod
    def _validate_version() -> None:
        import qlib

        actual = qlib.__version__.split("+")[0]
        if actual != EXPECTED_QLIB_VERSION:
            raise RuntimeError(
                f"Qlib package/collector mismatch: expected {EXPECTED_QLIB_VERSION}, got {actual}"
            )

    @staticmethod
    @contextmanager
    def _baostock_session() -> Iterator[None]:
        import baostock as bs

        result = bs.login()
        if result.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {result.error_code} {result.error_msg}")
        try:
            yield
        finally:
            bs.logout()

    def collect_csi500_snapshot(self, as_of: str | date) -> CollectedArtifact:
        """Collect one Baostock CSI500 snapshot through Qlib's collector."""

        from data_collector.cn_index.collector import CSI500Index

        requested_date = pd.Timestamp(as_of).normalize()
        with self._baostock_session():
            frame = CSI500Index.get_data_from_baostock(requested_date.date())

        if frame.empty:
            raise RuntimeError(f"Empty CSI500 snapshot for {requested_date.date()}")
        if len(frame) != 500:
            raise RuntimeError(
                f"Unexpected CSI500 constituent count for {requested_date.date()}: {len(frame)}"
            )

        frame = frame.rename(columns={"date": "snapshot_date", "symbol": "instrument"})
        frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"])
        if frame["snapshot_date"].max() > requested_date:
            raise RuntimeError("CSI500 source returned a snapshot after the requested as-of date")
        frame.insert(0, "requested_as_of", requested_date)
        frame["source"] = "qlib_v0.9.7_baostock_query_zz500_stocks"

        target = self.raw_root / "csi500" / f"snapshot_requested_{requested_date:%Y-%m-%d}.csv"
        return self._write_artifact(frame, target, {
            "dataset": "csi500_membership_snapshot",
            "requested_as_of": requested_date.strftime("%Y-%m-%d"),
            "source_snapshot_dates": sorted(frame["snapshot_date"].dt.strftime("%Y-%m-%d").unique()),
            "pit_quality": "weekly_candidate_requires_official_effective_date_validation",
        })

    def collect_pit_symbol(self, symbol: str, start: str, end: str) -> CollectedArtifact:
        """Collect Baostock PIT fundamentals using Qlib's four native queries.

        The public Qlib wrapper enumerates the full A-share universe before
        applying ``symbol_regex``.  For a targeted/incremental pipeline this is
        unnecessary, so the native query functions are called directly.
        """

        from data_collector.pit.collector import PitCollector

        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        if end_ts < start_ts:
            raise ValueError("end must be on or after start")

        normalized_symbol = symbol.lower()
        if "." not in normalized_symbol:
            raise ValueError("PIT symbol must use Qlib form such as 600519.ss")
        code, exchange = normalized_symbol.split(".", 1)
        baostock_symbol = f"{'sh' if exchange == 'ss' else 'sz'}.{code}"

        with self._baostock_session():
            parts = {
                "performance_express": PitCollector.get_performance_express_report_df(
                    baostock_symbol, start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")
                ),
                "profit": PitCollector.get_profit_df(
                    baostock_symbol, start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")
                ),
                "forecast": PitCollector.get_forecast_report_df(
                    baostock_symbol, start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")
                ),
                "growth": PitCollector.get_growth_df(
                    baostock_symbol, start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")
                ),
            }

        frames: list[pd.DataFrame] = []
        endpoint_counts: dict[str, int] = {}
        for endpoint, part in parts.items():
            part = part.copy()
            endpoint_counts[endpoint] = len(part)
            if part.empty:
                continue
            part["endpoint"] = endpoint
            frames.append(part)

        if frames:
            frame = pd.concat(frames, ignore_index=True, sort=False)
            frame["date"] = pd.to_datetime(frame["date"])
            frame["period"] = pd.to_datetime(frame["period"])
            # Enforce the user's as-of boundary even if an upstream API leaks a
            # later publication into the response window.
            frame = frame[(frame["date"] >= start_ts) & (frame["date"] <= end_ts)].copy()
            frame.insert(0, "instrument", normalized_symbol)
            frame["source"] = "qlib_v0.9.7_baostock_pit"
            frame = frame.sort_values(["date", "period", "field", "endpoint"]).reset_index(drop=True)
        else:
            frame = pd.DataFrame(
                columns=["instrument", "date", "period", "value", "field", "endpoint", "source"]
            )

        target = self.raw_root / "pit" / f"{normalized_symbol}_{start_ts:%Y-%m-%d}_{end_ts:%Y-%m-%d}.csv"
        return self._write_artifact(frame, target, {
            "dataset": "fundamentals_pit_candidate",
            "symbol": normalized_symbol,
            "requested_start": start_ts.strftime("%Y-%m-%d"),
            "requested_end": end_ts.strftime("%Y-%m-%d"),
            "raw_endpoint_counts_before_asof_filter": endpoint_counts,
            "pit_filter": "publication date is within requested inclusive range",
        })

    def collect_yahoo_daily(self, symbol: str, start: str, end: str) -> CollectedArtifact:
        """Collect one Yahoo daily-bar slice through Qlib's Yahoo collector."""

        from data_collector.yahoo.collector import YahooCollector

        frame = YahooCollector.get_data_from_remote(symbol, "1d", start, end)
        if frame is None or frame.empty:
            raise RuntimeError(f"Empty Yahoo daily data for {symbol} {start}..{end}")
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame["source"] = "qlib_v0.9.7_yahooquery"

        safe_symbol = symbol.lower().replace(".", "_")
        target = self.raw_root / "yahoo_daily" / f"{safe_symbol}_{start}_{end}.csv"
        return self._write_artifact(frame, target, {
            "dataset": "stock_daily_fallback",
            "symbol": symbol,
            "requested_start": start,
            "requested_end": end,
            "price_semantics": {
                "open_high_low_close": "Yahoo raw daily prices",
                "adjclose": "Yahoo adjusted close",
            },
        })

    def collect_baostock_index_daily(
        self, symbol: str, start: str, end: str
    ) -> CollectedArtifact:
        """Collect a mainland index through Baostock for use as a benchmark."""

        import baostock as bs

        normalized = symbol.upper().replace(".", "")
        if len(normalized) != 8 or not normalized.startswith(("SH", "SZ")):
            raise ValueError("Index symbol must use Qlib form such as SH000905")
        baostock_symbol = f"{normalized[:2].lower()}.{normalized[2:]}"
        yahoo_symbol = f"{normalized[2:]}.{'SS' if normalized.startswith('SH') else 'SZ'}"
        with self._baostock_session():
            result = bs.query_history_k_data_plus(
                baostock_symbol,
                "date,open,high,low,close,volume",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="3",
            )
            if result.error_code != "0":
                raise RuntimeError(
                    f"Baostock index query failed: {result.error_code} {result.error_msg}"
                )
            # Baostock's get_data() still calls DataFrame.append when a query
            # spans multiple pages, which is incompatible with pandas 2.x.
            rows: list[list[str]] = []
            while result.next():
                rows.append(result.get_row_data())
            frame = pd.DataFrame(rows, columns=result.fields)
        if frame.empty:
            raise RuntimeError(f"Empty Baostock index data for {symbol} {start}..{end}")
        frame.insert(0, "symbol", yahoo_symbol)
        frame["date"] = pd.to_datetime(frame["date"])
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["adjclose"] = frame["close"]
        frame["source"] = "qlib_v0.9.7_baostock_index_history"

        safe_symbol = yahoo_symbol.lower().replace(".", "_")
        target = self.raw_root / "yahoo_daily" / f"{safe_symbol}_{start}_{end}.csv"
        return self._write_artifact(
            frame,
            target,
            {
                "dataset": "index_daily_benchmark",
                "symbol": yahoo_symbol,
                "requested_start": start,
                "requested_end": end,
                "price_semantics": {
                    "open_high_low_close": "Baostock unadjusted index levels",
                    "adjclose": "same as close for an index",
                },
            },
        )

    @staticmethod
    def _write_artifact(frame: pd.DataFrame, target: Path, metadata: dict) -> CollectedArtifact:
        target.parent.mkdir(parents=True, exist_ok=True)
        csv_bytes = frame.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")
        digest = hashlib.sha256(csv_bytes).hexdigest()
        data_tmp = target.with_name(f"{target.name}.tmp")
        data_tmp.write_bytes(csv_bytes)
        os.replace(data_tmp, target)

        metadata_path = target.with_suffix(".metadata.json")
        payload = {
            **metadata,
            "row_count": len(frame),
            "sha256": digest,
            "data_file": target.name,
            "qlib_version": EXPECTED_QLIB_VERSION,
        }
        metadata_tmp = metadata_path.with_name(f"{metadata_path.name}.tmp")
        metadata_tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(metadata_tmp, metadata_path)
        return CollectedArtifact(target, metadata_path, len(frame), digest)

