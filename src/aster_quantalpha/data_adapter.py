"""Convert Aster source checkpoints into QuantaAlpha/Qlib input formats."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


PRICE_COLUMNS = ("open", "high", "low", "close")
HDF_COLUMNS = ("$open", "$high", "$low", "$close", "$volume", "$return")


def to_trading_date(values: pd.Series) -> pd.Series:
    """Parse daily labels without allowing an attached timezone to shift the date."""
    labels = values.astype("string").str.strip().str.slice(0, 10)
    return pd.to_datetime(labels, format="%Y-%m-%d", errors="coerce")


def to_qlib_instrument(symbol: str) -> str:
    value = str(symbol).strip().upper()
    if value.startswith(("SH", "SZ")) and len(value) == 8:
        return value
    if value.endswith(".SS"):
        return f"SH{value[:-3]}"
    if value.endswith(".SZ"):
        return f"SZ{value[:-3]}"
    if value.isdigit() and len(value) == 6:
        return f"SH{value}" if value.startswith(("5", "6", "9")) else f"SZ{value}"
    raise ValueError(f"Unsupported A-share symbol: {symbol!r}")


@dataclass(frozen=True)
class AdaptedArtifacts:
    full_hdf: Path
    debug_hdf: Path
    qlib_dir: Path | None
    membership_file: Path | None
    manifest_path: Path
    rows: int
    instruments: int


class QuantaAlphaDataAdapter:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.raw_root = self.project_root / "data" / "raw" / "qlib_full"
        self.output_root = self.project_root / "data" / "quantalpha"
        self.vendor_qlib = self.project_root / "vendor" / "qlib-v0.9.7"

    def build(
        self,
        *,
        source_root: Path | None = None,
        output_root: Path | None = None,
        debug_instruments: int = 25,
        limit_files: int | None = None,
        build_qlib: bool = True,
        sample_fallback: bool = False,
    ) -> AdaptedArtifacts:
        source_root = Path(source_root or self.raw_root / "yahoo_daily")
        output_root = Path(output_root or self.output_root)
        files = sorted(source_root.glob("*.csv"))
        source_kind = "qlib_full_yahoo_daily"
        if not files and sample_fallback:
            source_root = self.project_root / "data" / "raw" / "qlib_collector" / "yahoo_daily"
            files = sorted(source_root.glob("*.csv"))
            source_kind = "qlib_collector_smoke_fallback"
        if limit_files is not None:
            files = files[:limit_files]
        if not files:
            raise RuntimeError(f"No Aster Yahoo daily CSV files found under {source_root}")

        qlib_panel = self.load_market_panel(files)
        if qlib_panel.empty:
            raise RuntimeError("Market adapter produced an empty panel")
        benchmark = qlib_panel.loc[
            qlib_panel.index.get_level_values("instrument") == "SH000905"
        ]
        panel = qlib_panel.loc[
            qlib_panel.index.get_level_values("instrument") != "SH000905"
        ]
        if panel.empty:
            raise RuntimeError("Market adapter produced no constituent rows after benchmark exclusion")

        full_dir = output_root / "factor_implementation_source_data"
        debug_dir = output_root / "factor_implementation_source_data_debug"
        full_hdf = full_dir / "daily_pv.h5"
        debug_hdf = debug_dir / "daily_pv.h5"
        self._write_hdf(panel, full_hdf)
        selected = sorted(panel.index.get_level_values("instrument").unique())[:debug_instruments]
        debug = panel.loc[pd.IndexSlice[:, selected], :]
        self._write_hdf(debug, debug_hdf)
        self._write_readme(full_dir)
        self._write_readme(debug_dir)

        membership_file: Path | None = None
        qlib_dir: Path | None = None
        if build_qlib:
            staging = output_root / "qlib_csv"
            self.write_qlib_csv(qlib_panel, staging)
            qlib_dir = output_root / "qlib" / "cn_data"
            self.dump_qlib(staging, qlib_dir)
            membership_file = self.write_csi500_membership(
                self.raw_root / "csi500_snapshots",
                qlib_dir / "instruments" / "csi500.txt",
            )

        manifest_path = output_root / "manifest.json"
        expected_path = self.raw_root / "csi500_historical_union.csv"
        expected_instruments: set[str] = set()
        if expected_path.exists():
            expected = pd.read_csv(expected_path, usecols=["instrument"])
            expected_instruments = set(expected["instrument"].map(to_qlib_instrument))
        actual_instruments = set(panel.index.get_level_values("instrument"))
        missing_instruments = sorted(expected_instruments.difference(actual_instruments))
        payload = {
            "adapter": "aster_quantalpha_v1",
            "source_kind": source_kind,
            "source_root": str(source_root.resolve()),
            "source_file_count": len(files),
            "rows": len(panel),
            "instruments": panel.index.get_level_values("instrument").nunique(),
            "expected_instruments": len(expected_instruments),
            "market_coverage_ratio": (
                None
                if not expected_instruments
                else round(len(expected_instruments & actual_instruments) / len(expected_instruments), 6)
            ),
            "missing_instruments": missing_instruments,
            "benchmark": "SH000905",
            "benchmark_rows": len(benchmark),
            "benchmark_in_factor_hdf": False,
            "date_start": str(panel.index.get_level_values("datetime").min().date()),
            "date_end": str(panel.index.get_level_values("datetime").max().date()),
            "index_names": list(panel.index.names),
            "columns": list(panel.columns),
            "price_semantics": "Yahoo OHLC multiplied by adjclose/close; close equals adjclose",
            "volume_semantics": "Yahoo raw reported volume; not dividend-adjusted",
            "return_semantics": "per-instrument adjusted-close pct_change; first observation is 0",
            "membership_semantics": "weekly PIT candidate from Qlib/Baostock snapshots",
            "full_hdf": str(full_hdf.resolve()),
            "full_hdf_sha256": self._sha256(full_hdf),
            "debug_hdf": str(debug_hdf.resolve()),
            "debug_hdf_sha256": self._sha256(debug_hdf),
            "qlib_dir": None if qlib_dir is None else str(qlib_dir.resolve()),
            "membership_file": None if membership_file is None else str(membership_file.resolve()),
        }
        self._write_json(manifest_path, payload)
        return AdaptedArtifacts(
            full_hdf=full_hdf,
            debug_hdf=debug_hdf,
            qlib_dir=qlib_dir,
            membership_file=membership_file,
            manifest_path=manifest_path,
            rows=len(panel),
            instruments=payload["instruments"],
        )

    @staticmethod
    def load_market_panel(files: list[Path]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        required = {"symbol", "date", "open", "high", "low", "close", "volume", "adjclose"}
        for path in files:
            frame = pd.read_csv(path)
            missing = required.difference(frame.columns)
            if missing:
                raise ValueError(f"{path} is missing columns: {sorted(missing)}")
            frame = frame.loc[:, sorted(required)].copy()
            frame["datetime"] = to_trading_date(frame["date"])
            frame["instrument"] = frame["symbol"].map(to_qlib_instrument)
            for column in (*PRICE_COLUMNS, "volume", "adjclose"):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            factor = frame["adjclose"].div(frame["close"]).replace([np.inf, -np.inf], np.nan)
            factor = factor.where(factor.gt(0))
            for column in PRICE_COLUMNS:
                frame[f"${column}"] = frame[column] * factor
            frame["$close"] = frame["adjclose"]
            frame["$volume"] = frame["volume"]
            frames.append(frame[["datetime", "instrument", *HDF_COLUMNS[:-1]]])

        panel = pd.concat(frames, ignore_index=True)
        panel = panel.dropna(subset=["datetime", "instrument", "$close"])
        panel = panel.sort_values(["instrument", "datetime"])
        panel = panel.drop_duplicates(["datetime", "instrument"], keep="last")
        panel["$return"] = (
            panel.groupby("instrument", sort=False)["$close"]
            .pct_change(fill_method=None)
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
        )
        panel = panel.set_index(["datetime", "instrument"]).sort_index()
        panel = panel.loc[:, list(HDF_COLUMNS)].astype("float64")
        return panel

    @staticmethod
    def write_qlib_csv(panel: pd.DataFrame, target_dir: Path) -> None:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        data = panel.reset_index().rename(
            columns={
                "datetime": "date",
                "$open": "open",
                "$high": "high",
                "$low": "low",
                "$close": "close",
                "$volume": "volume",
            }
        )
        data["factor"] = 1.0
        for instrument, group in data.groupby("instrument", sort=True):
            output = target_dir / f"{instrument.lower()}.csv"
            columns = ["date", "instrument", "open", "high", "low", "close", "volume", "factor"]
            group.loc[:, columns].rename(columns={"instrument": "symbol"}).to_csv(
                output, index=False, lineterminator="\n"
            )

    def dump_qlib(self, csv_dir: Path, qlib_dir: Path) -> None:
        scripts_dir = self.vendor_qlib / "scripts"
        if not scripts_dir.exists():
            raise FileNotFoundError(f"Vendored Qlib scripts not found: {scripts_dir}")
        sys.path.insert(0, str(scripts_dir))
        try:
            from dump_bin import DumpDataAll

            if qlib_dir.exists():
                shutil.rmtree(qlib_dir)
            dumper = DumpDataAll(
                data_path=str(csv_dir),
                qlib_dir=str(qlib_dir),
                freq="day",
                max_workers=4,
                date_field_name="date",
                symbol_field_name="symbol",
                include_fields="open,high,low,close,volume,factor",
            )
            dumper.dump()
        finally:
            if sys.path and sys.path[0] == str(scripts_dir):
                sys.path.pop(0)

    @staticmethod
    def write_csi500_membership(snapshot_dir: Path, target: Path) -> Path:
        observations: list[pd.DataFrame] = []
        for path in sorted(snapshot_dir.glob("snapshot_requested_*.csv")):
            frame = pd.read_csv(path, usecols=["requested_as_of", "instrument"])
            frame["requested_as_of"] = to_trading_date(frame["requested_as_of"])
            frame["instrument"] = frame["instrument"].map(to_qlib_instrument)
            observations.append(frame)
        if not observations:
            raise RuntimeError(f"No membership snapshots under {snapshot_dir}")
        history = pd.concat(observations, ignore_index=True).drop_duplicates()
        segments: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
        for instrument, group in history.groupby("instrument"):
            dates = sorted(group["requested_as_of"].dropna().unique())
            if not dates:
                continue
            start = previous = pd.Timestamp(dates[0])
            for value in dates[1:]:
                current = pd.Timestamp(value)
                if current - previous > pd.Timedelta(days=14):
                    segments.append((instrument, start, previous))
                    start = current
                previous = current
            segments.append((instrument, start, previous))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for instrument, start, end in sorted(segments):
                handle.write(f"{instrument}\t{start:%Y-%m-%d}\t{end:%Y-%m-%d}\n")
        os.replace(temporary, target)
        return target

    @staticmethod
    def _write_hdf(frame: pd.DataFrame, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        frame.to_hdf(temporary, key="data", mode="w", format="table", complevel=5, complib="zlib")
        os.replace(temporary, target)

    @staticmethod
    def _write_readme(target_dir: Path) -> None:
        (target_dir / "README.md").write_text(
            "# Aster QuantaAlpha factor input\n\n"
            "`daily_pv.h5` uses HDF key `data`, MultiIndex "
            "`(datetime, instrument)`, and columns `$open`, `$high`, `$low`, "
            "`$close`, `$volume`, `$return`. See the deployment manifest for semantics.\n",
            encoding="utf-8",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--debug-instruments", type=int, default=25)
    parser.add_argument("--limit-files", type=int)
    parser.add_argument("--skip-qlib", action="store_true")
    parser.add_argument("--sample-fallback", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    adapter = QuantaAlphaDataAdapter(args.project_root)
    result = adapter.build(
        source_root=args.source_root,
        output_root=args.output_root,
        debug_instruments=args.debug_instruments,
        limit_files=args.limit_files,
        build_qlib=not args.skip_qlib,
        sample_fallback=args.sample_fallback,
    )
    print(json.dumps({key: str(value) for key, value in asdict(result).items()}, indent=2))


if __name__ == "__main__":
    main()
