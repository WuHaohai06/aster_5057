"""Build a point-in-time CSI500 universe candidate from dated snapshots."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from .io import instrument_from_code, sha256_file, write_json_atomic


REQUIRED_ADJUSTMENT_COLUMNS = {"effective_date", "instrument", "action", "source_id"}


def load_snapshots(snapshot_root: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(snapshot_root.glob("snapshot_requested_*.csv")):
        frame = pd.read_csv(
            path,
            usecols=["requested_as_of", "snapshot_date", "instrument"],
            dtype=str,
        )
        frame["snapshot_file"] = path.name
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"no CSI500 snapshots found under {snapshot_root}")
    result = pd.concat(frames, ignore_index=True)
    result["requested_as_of"] = pd.to_datetime(result["requested_as_of"], errors="raise")
    result["snapshot_date"] = pd.to_datetime(result["snapshot_date"], errors="raise")
    result["instrument"] = result["instrument"].map(instrument_from_code)
    if (result["snapshot_date"] > result["requested_as_of"]).any():
        raise ValueError("a source snapshot is after its requested_as_of boundary")
    result = result.drop_duplicates(["requested_as_of", "instrument"])
    return result.sort_values(["requested_as_of", "instrument"]).reset_index(drop=True)


def apply_official_adjustments(
    snapshots: pd.DataFrame, adjustments: pd.DataFrame
) -> pd.DataFrame:
    if adjustments.empty:
        return snapshots.copy()
    missing = REQUIRED_ADJUSTMENT_COLUMNS.difference(adjustments.columns)
    if missing:
        raise ValueError(f"official adjustments are missing columns: {sorted(missing)}")
    changes = adjustments.copy()
    changes["effective_date"] = pd.to_datetime(changes["effective_date"], errors="raise")
    changes["instrument"] = changes["instrument"].map(instrument_from_code)
    changes["action"] = changes["action"].str.lower()
    if not changes["action"].isin(["add", "remove"]).all():
        raise ValueError("official adjustment action must be add or remove")
    dates = sorted(snapshots["requested_as_of"].unique())
    snapshot_sets = {
        date: set(
            snapshots.loc[snapshots["requested_as_of"] == date, "instrument"].tolist()
        )
        for date in dates
    }
    for row in changes.sort_values(["effective_date", "instrument"]).itertuples():
        for date in dates:
            if pd.Timestamp(date) < row.effective_date:
                continue
            if row.action == "add":
                snapshot_sets[date].add(row.instrument)
            else:
                snapshot_sets[date].discard(row.instrument)
    rows = []
    source_dates = (
        snapshots.groupby("requested_as_of")["snapshot_date"].max().to_dict()
    )
    for date in dates:
        for instrument in sorted(snapshot_sets[date]):
            rows.append(
                {
                    "requested_as_of": pd.Timestamp(date),
                    "snapshot_date": source_dates[date],
                    "instrument": instrument,
                    "snapshot_file": "official-adjustment-overlay",
                }
            )
    return pd.DataFrame(rows)


def snapshots_to_intervals(
    snapshots: pd.DataFrame, *, requested_end: pd.Timestamp
) -> pd.DataFrame:
    dates = pd.DatetimeIndex(sorted(snapshots["requested_as_of"].unique()))
    index_by_date = {date: index for index, date in enumerate(dates)}
    presence = {
        instrument: sorted(index_by_date[pd.Timestamp(value)] for value in group)
        for instrument, group in snapshots.groupby("instrument")["requested_as_of"]
    }
    rows = []
    for instrument, indices in sorted(presence.items()):
        run_start = indices[0]
        previous = indices[0]
        for current in indices[1:] + [None]:
            if current is not None and current == previous + 1:
                previous = current
                continue
            start = dates[run_start]
            next_index = previous + 1
            end = (
                dates[next_index] - pd.Timedelta(days=1)
                if next_index < len(dates)
                else requested_end
            )
            rows.append(
                {
                    "instrument": instrument,
                    "effective_start": start.normalize(),
                    "effective_end": pd.Timestamp(end).normalize(),
                    "available_at": start.normalize(),
                    "source": "qlib_baostock_weekly_candidate",
                }
            )
            if current is None:
                break
            run_start = current
            previous = current
    return pd.DataFrame(rows).sort_values(
        ["effective_start", "instrument"]
    ).reset_index(drop=True)


def _write_parquet_atomic(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, target)


def build_pit_universe(
    *,
    snapshot_root: Path,
    output_root: Path,
    requested_end: str,
    official_adjustments: Path | None = None,
) -> dict:
    snapshots = load_snapshots(snapshot_root)
    adjustments = pd.DataFrame()
    if official_adjustments is not None:
        adjustments = pd.read_csv(official_adjustments, dtype=str)
        snapshots = apply_official_adjustments(snapshots, adjustments)
    intervals = snapshots_to_intervals(
        snapshots, requested_end=pd.Timestamp(requested_end)
    )
    snapshots_path = output_root / "snapshots.parquet"
    intervals_path = output_root / "intervals.parquet"
    _write_parquet_atomic(snapshots, snapshots_path)
    _write_parquet_atomic(intervals, intervals_path)
    payload = {
        "dataset": "csi500_pit_universe_candidate",
        "quality": (
            "official_adjustments_applied"
            if official_adjustments is not None
            else "weekly_candidate_requires_official_effective_date_correction"
        ),
        "snapshot_count": int(snapshots["requested_as_of"].nunique()),
        "instrument_count": int(snapshots["instrument"].nunique()),
        "snapshot_rows": len(snapshots),
        "interval_rows": len(intervals),
        "first_available_at": snapshots["requested_as_of"].min().date().isoformat(),
        "last_available_at": snapshots["requested_as_of"].max().date().isoformat(),
        "requested_end": requested_end,
        "official_adjustment_rows": len(adjustments),
        "official_adjustments": str(official_adjustments) if official_adjustments else None,
        "files": {
            snapshots_path.name: sha256_file(snapshots_path),
            intervals_path.name: sha256_file(intervals_path),
        },
    }
    write_json_atomic(output_root / "manifest.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--requested-end", required=True)
    parser.add_argument("--official-adjustments", type=Path)
    args = parser.parse_args()
    payload = build_pit_universe(
        snapshot_root=args.snapshot_root,
        output_root=args.output_root,
        requested_end=args.requested_end,
        official_adjustments=args.official_adjustments,
    )
    print(payload)


if __name__ == "__main__":
    main()
