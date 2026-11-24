"""Canonical factor store, QuantaAlpha ingestion and PIT financial factors."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .io import instrument_from_code, sha256_file, write_json_atomic


FACTOR_COLUMNS = [
    "date", "available_at", "instrument", "factor_id", "factor_group", "value",
    "origin", "source_id", "version",
]


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def build_financial_factors(*, pit_root: Path, output_root: Path) -> dict:
    files = sorted(pit_root.glob("*.csv"))
    if not files:
        raise RuntimeError(f"no PIT financial CSV files under {pit_root}")
    frames = []
    for path in files:
        frame = pd.read_csv(path)
        required = {"instrument", "date", "period", "value", "field", "endpoint", "source"}
        if required.difference(frame.columns):
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
        frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.normalize()
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame.dropna(subset=["date", "period", "value"])
        frame["instrument"] = frame["instrument"].map(instrument_from_code)
        frame["factor_id"] = "fin_" + frame["field"].str.lower()
        frame["factor_group"] = "financial_" + frame["endpoint"].str.lower()
        frame["available_at"] = frame["date"]
        frame["origin"] = "qlib_baostock_pit"
        frame["source_id"] = (
            "financial:" + frame["instrument"] + ":" + frame["period"].dt.strftime("%Y-%m-%d")
            + ":" + frame["field"]
        )
        frame["version"] = "aster-financial-pit-v1"
        frames.append(frame[[*FACTOR_COLUMNS, "period", "endpoint", "field"]])
    if not frames:
        raise RuntimeError("all PIT files failed the canonical schema contract")
    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["date", "instrument", "factor_id", "period"])
    result = result.drop_duplicates(["date", "instrument", "factor_id"], keep="last")
    path = output_root / "financial_factors.parquet"
    _write_parquet(result, path)
    manifest = {
        "dataset": "aster-financial-pit-factors-v1",
        "rows": len(result),
        "instruments": result["instrument"].nunique(),
        "factor_ids": sorted(result["factor_id"].unique()),
        "available_at_semantics": "public disclosure date from Baostock/Qlib PIT endpoint",
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
    }
    write_json_atomic(output_root / "financial_manifest.json", manifest)
    return manifest


def ingest_factor_file(
    *, input_path: Path, output_root: Path, origin: str = "quantaalpha", factor_id: str | None = None
) -> dict:
    """Normalize a QuantaAlpha CSV/Parquet result without guessing its economics."""

    frame = pd.read_parquet(input_path) if input_path.suffix.lower() == ".parquet" else pd.read_csv(input_path)
    aliases = {"datetime": "date", "symbol": "instrument", "score": "value", "factor": "value"}
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame and value not in frame})
    if "factor_id" not in frame:
        if not factor_id:
            raise ValueError("input has no factor_id; pass --factor-id")
        frame["factor_id"] = factor_id
    required = {"date", "instrument", "value", "factor_id"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"factor file is missing {sorted(missing)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["available_at"] = pd.to_datetime(frame.get("available_at", frame["date"]), errors="coerce").dt.normalize()
    if (frame["available_at"] > frame["date"]).any():
        raise ValueError("available_at cannot be after the signal date")
    frame["instrument"] = frame["instrument"].map(instrument_from_code)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "available_at", "value"])
    frame["factor_group"] = frame.get("factor_group", frame["factor_id"])
    frame["origin"] = origin
    digest = sha256_file(input_path)
    frame["source_id"] = frame.get("source_id", "factor-file:" + digest)
    frame["version"] = frame.get("version", "aster-factor-ingest-v1")
    frame = frame[FACTOR_COLUMNS].sort_values(["date", "instrument", "factor_id"])
    frame = frame.drop_duplicates(["date", "instrument", "factor_id"], keep="last")
    safe_name = input_path.stem.replace(" ", "_")
    output = output_root / f"{safe_name}.parquet"
    _write_parquet(frame, output)
    registry = []
    for item in sorted(frame["factor_id"].unique()):
        group = str(frame.loc[frame["factor_id"] == item, "factor_group"].iloc[0])
        registry.append({
            "factor_id": str(item), "factor_group": group,
            "description": f"Imported {origin} factor {item}", "origin": origin,
            "formula": "See immutable source artifact " + digest,
            "approval_status": "candidate",
        })
    manifest = {
        "dataset": "aster-canonical-factor-v1", "source": str(input_path.resolve()),
        "source_sha256": digest, "output": str(output.resolve()), "output_sha256": sha256_file(output),
        "rows": len(frame), "factors": registry,
    }
    write_json_atomic(output_root / f"{safe_name}.manifest.json", manifest)
    return manifest
