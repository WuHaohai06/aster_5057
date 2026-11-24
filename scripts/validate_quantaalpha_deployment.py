"""Validate the deployed QuantaAlpha stack against an adapted Aster dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D
from quantaalpha.factors.coder.function_lib import TS_MEAN


def validate(dataset_root: Path) -> dict[str, object]:
    manifest_path = dataset_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hdf_path = dataset_root / "factor_implementation_source_data" / "daily_pv.h5"
    provider_uri = dataset_root / "qlib" / "cn_data"

    panel = pd.read_hdf(hdf_path, key="data")
    expected_columns = {"$open", "$high", "$low", "$close", "$volume", "$return"}
    if panel.index.names != ["datetime", "instrument"]:
        raise AssertionError(f"Unexpected HDF index: {panel.index.names}")
    if not expected_columns.issubset(panel.columns):
        raise AssertionError(f"Missing HDF columns: {sorted(expected_columns.difference(panel.columns))}")
    if panel.empty or panel.index.has_duplicates:
        raise AssertionError("HDF panel is empty or has duplicate index rows")

    rolling = TS_MEAN(panel[["$close"]], 3)
    if len(rolling) != len(panel) or rolling.dropna().empty:
        raise AssertionError("QuantaAlpha TS_MEAN did not produce usable factor values")

    instrument = str(panel.index.get_level_values("instrument")[0])
    start = panel.index.get_level_values("datetime").min()
    end = panel.index.get_level_values("datetime").max()
    qlib.init(provider_uri=str(provider_uri), region=REG_CN)
    features = D.features(
        [instrument],
        ["$open", "$close", "$volume"],
        start_time=start,
        end_time=end,
        freq="day",
    )
    if features.empty or features["$close"].dropna().empty:
        raise AssertionError("Qlib provider could not read the adapted binary features")

    return {
        "status": "ok",
        "dataset_root": str(dataset_root.resolve()),
        "manifest_rows": manifest["rows"],
        "hdf_rows": len(panel),
        "instrument": instrument,
        "date_start": str(start.date()),
        "date_end": str(end.date()),
        "factor_non_null": int(rolling.notna().sum().sum()),
        "qlib_rows": len(features),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
