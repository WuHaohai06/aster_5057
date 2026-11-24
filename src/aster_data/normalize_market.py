"""Normalize AKShare-primary and Yahoo-fallback bars into one PIT market panel."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .io import instrument_from_code, sha256_file, write_json_atomic


CANONICAL_COLUMNS = [
    "date",
    "instrument",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_pct",
    "source",
    "adjustment",
    "quality_flag",
]


def _akshare_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["instrument"] = frame["instrument"].map(instrument_from_code)
    frame["source_priority"] = 0
    for column in ("amount", "turnover_pct"):
        if column not in frame:
            frame[column] = np.nan
    if "quality_flag" not in frame:
        frame["quality_flag"] = ""
    return frame[CANONICAL_COLUMNS + ["source_priority"]]


def _yahoo_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS + ["source_priority"])
    ratio = pd.to_numeric(frame["adjclose"], errors="coerce").div(
        pd.to_numeric(frame["close"], errors="coerce").replace(0.0, np.nan)
    )
    result = pd.DataFrame(
        {
            "date": frame["date"],
            "instrument": frame["symbol"].map(instrument_from_code),
            "open": pd.to_numeric(frame["open"], errors="coerce") * ratio,
            "high": pd.to_numeric(frame["high"], errors="coerce") * ratio,
            "low": pd.to_numeric(frame["low"], errors="coerce") * ratio,
            "close": pd.to_numeric(frame["adjclose"], errors="coerce"),
            "volume": pd.to_numeric(frame["volume"], errors="coerce"),
            "amount": np.nan,
            "turnover_pct": np.nan,
            "source": "qlib_v0.9.7_yahooquery_adjusted_fallback",
            "adjustment": "yahoo_adjclose_ratio",
            "source_priority": 1,
        }
    )
    upper = result[["open", "high", "low", "close"]].max(axis=1)
    lower = result[["open", "high", "low", "close"]].min(axis=1)
    inconsistent = (result["high"] < upper) | (result["low"] > lower)
    result["quality_flag"] = np.where(inconsistent, "source_ohlc_range_repaired", "")
    result["high"] = upper
    result["low"] = lower
    return result


def _membership_flag(frame: pd.DataFrame, intervals: pd.DataFrame) -> pd.Series:
    flag = pd.Series(False, index=frame.index)
    if intervals.empty:
        return flag
    grouped = intervals.groupby("instrument")
    for instrument, row_indices in frame.groupby("instrument").groups.items():
        if instrument not in grouped.groups:
            continue
        dates = frame.loc[row_indices, "date"]
        member = pd.Series(False, index=row_indices)
        for item in grouped.get_group(instrument).itertuples():
            member |= dates.between(item.effective_start, item.effective_end)
        flag.loc[row_indices] = member
    return flag


def normalize_market_store(
    *,
    akshare_root: Path,
    yahoo_root: Path,
    output_root: Path,
    universe_intervals: Path | None = None,
    limit_instruments: int | None = None,
) -> dict:
    frames: list[pd.DataFrame] = []
    input_files: list[Path] = []
    akshare_paths = sorted(akshare_root.glob("*.csv")) if akshare_root.exists() else []
    yahoo_paths = sorted(yahoo_root.glob("*.csv")) if yahoo_root.exists() else []
    if limit_instruments is not None:
        akshare_paths = akshare_paths[:limit_instruments]
        # Retain Yahoo files for the same instruments plus enough fallback samples.
        selected = {
            instrument_from_code(pd.read_csv(path, nrows=1)["instrument"].iloc[0])
            for path in akshare_paths
        }
        yahoo_paths = [
            path
            for path in yahoo_paths
            if instrument_from_code(pd.read_csv(path, nrows=1)["symbol"].iloc[0]) in selected
        ][:limit_instruments]
    for path in akshare_paths:
        frames.append(_akshare_frame(path))
        input_files.append(path)
    for path in yahoo_paths:
        frames.append(_yahoo_frame(path))
        input_files.append(path)
    if not frames:
        raise FileNotFoundError("no AKShare or Yahoo market files were found")
    market = pd.concat(frames, ignore_index=True)
    # Source files may mix YYYY-MM-DD and close timestamps with an explicit
    # Asia/Shanghai offset. The first ten characters are the exchange date;
    # converting through UTC could incorrectly move it to the previous day.
    exchange_dates = market["date"].astype(str).str.slice(0, 10)
    market["date"] = pd.to_datetime(
        exchange_dates, format="%Y-%m-%d", errors="raise"
    ).dt.normalize()
    numeric = ["open", "high", "low", "close", "volume", "amount", "turnover_pct"]
    market[numeric] = market[numeric].apply(pd.to_numeric, errors="coerce")
    market = market.dropna(subset=["open", "high", "low", "close"])
    market = market.sort_values(
        ["instrument", "date", "source_priority"]
    ).drop_duplicates(["instrument", "date"], keep="first")
    market = market.sort_values(["date", "instrument"]).reset_index(drop=True)
    if market.duplicated(["date", "instrument"]).any():
        raise ValueError("normalized market panel contains duplicate keys")
    if (market[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("normalized market panel contains non-positive prices")
    market["available_at"] = market["date"]
    intervals = pd.DataFrame()
    if universe_intervals is not None:
        intervals = pd.read_parquet(universe_intervals)
        intervals["effective_start"] = pd.to_datetime(intervals["effective_start"])
        intervals["effective_end"] = pd.to_datetime(intervals["effective_end"])
        market["csi500_member"] = _membership_flag(market, intervals)
    else:
        market["csi500_member"] = False
    market = market.drop(columns="source_priority")
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / "daily.parquet"
    temporary = target.with_name(target.name + ".tmp")
    market.to_parquet(temporary, index=False)
    os.replace(temporary, target)
    per_source = {str(key): int(value) for key, value in market["source"].value_counts().items()}
    payload = {
        "dataset": "aster_market_daily_v1",
        "primary_source": "AKShare Eastmoney adjusted bars",
        "fallback_source": "Yahoo adjusted-close-ratio bars",
        "rows": len(market),
        "instruments": int(market["instrument"].nunique()),
        "first_date": market["date"].min().date().isoformat(),
        "last_date": market["date"].max().date().isoformat(),
        "member_rows": int(market["csi500_member"].sum()),
        "quality_flag_rows": {
            str(key): int(value)
            for key, value in market.loc[market["quality_flag"].ne(""), "quality_flag"].value_counts().items()
        },
        "rows_by_source": per_source,
        "input_file_count": len(input_files),
        "input_digest_manifest_omitted": "input files remain immutable with per-file metadata",
        "files": {target.name: sha256_file(target)},
    }
    write_json_atomic(output_root / "manifest.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--akshare-root", type=Path, required=True)
    parser.add_argument("--yahoo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--universe-intervals", type=Path)
    parser.add_argument("--limit-instruments", type=int)
    args = parser.parse_args()
    result = normalize_market_store(
        akshare_root=args.akshare_root,
        yahoo_root=args.yahoo_root,
        output_root=args.output_root,
        universe_intervals=args.universe_intervals,
        limit_instruments=args.limit_instruments,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
