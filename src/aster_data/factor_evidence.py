"""Deterministic factor diagnostics and market evidence for the AI Council."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from aster_portfolio.factors import compute_price_volume_factors
from .io import sha256_file, write_json_atomic


def build_market_factors(*, market_path: Path, output_path: Path, as_of: str | None = None) -> dict:
    raw = pd.read_parquet(market_path)
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    if as_of is not None:
        raw = raw.loc[raw["date"] <= pd.Timestamp(as_of).normalize()]
    stock = raw.loc[(raw["instrument"] != "SH000905") & raw["csi500_member"].astype(bool)]
    instruments = sorted(stock["instrument"].unique())
    def pivot(column: str) -> pd.DataFrame:
        return raw.loc[raw["instrument"].isin(instruments)].pivot(index="date", columns="instrument", values=column).sort_index()
    eligibility = (
        stock.pivot(index="date", columns="instrument", values="csi500_member")
        .reindex(columns=instruments).astype("boolean").fillna(False).astype(bool)
    )
    factors = compute_price_volume_factors(
        close=pivot("close"), high=pivot("high"), low=pivot("low"), volume=pivot("volume")
    )
    rows = []
    for factor_id, panel in factors.items():
        mask = eligibility.reindex_like(panel).astype("boolean").fillna(False).astype(bool)
        panel = panel.where(mask)
        long = panel.stack(future_stack=True).rename("value").reset_index().dropna(subset=["value"])
        long["factor_id"] = factor_id
        long["factor_group"] = factor_id
        rows.append(long)
    frame = pd.concat(rows, ignore_index=True).dropna(subset=["value"])
    frame["available_at"] = frame["date"]
    frame["origin"] = "aster_deterministic_baseline"
    frame["source_id"] = "market:" + sha256_file(market_path)
    frame["version"] = "aster-pv-baseline-v1"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_path, index=False)
    return {"rows": len(frame), "factor_ids": sorted(factors), "path": str(output_path.resolve()), "sha256": sha256_file(output_path)}


def evaluate_factors(
    *, factor_paths: list[Path], market_path: Path, output_root: Path,
    as_of: str, horizon: int = 20, minimum_cross_section: int = 20,
) -> tuple[dict, dict]:
    cutoff = pd.Timestamp(as_of).normalize()
    market = pd.read_parquet(market_path)
    market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    market = market.loc[market["date"] <= cutoff].copy()
    close = market.pivot(index="date", columns="instrument", values="close").sort_index()
    future_return = close.shift(-horizon).div(close).sub(1.0)
    label_long = future_return.stack(future_stack=True).rename("label").reset_index()
    maturity = close.index.to_series().shift(-horizon)
    maturity_map = dict(zip(close.index, maturity))
    all_factors = pd.concat([pd.read_parquet(path) for path in factor_paths], ignore_index=True)
    all_factors["date"] = pd.to_datetime(all_factors["date"]).dt.normalize()
    all_factors["available_at"] = pd.to_datetime(all_factors["available_at"]).dt.normalize()
    all_factors = all_factors.loc[(all_factors["date"] <= cutoff) & (all_factors["available_at"] <= cutoff)]
    registry_items = []
    diagnostic_items = []
    panels: dict[str, pd.Series] = {}
    expected = market.loc[market["csi500_member"].astype(bool), ["date", "instrument"]].drop_duplicates()
    eligible = (
        expected.assign(eligible=1)
        .pivot(index="date", columns="instrument", values="eligible")
        .reindex(index=close.index, columns=close.columns)
        .fillna(0).astype(bool)
    )
    for factor_id, group in all_factors.groupby("factor_id", sort=True):
        factor_group = str(group["factor_group"].iloc[0])
        origin = str(group["origin"].iloc[0])
        registry_items.append({
            "factor_id": str(factor_id), "factor_group": factor_group,
            "description": f"Canonical {origin} factor {factor_id}", "origin": origin,
            "formula": f"version={group['version'].iloc[0]}", "approval_status": "approved",
        })
        # Canonical financial factors are disclosure events. Forward filling on
        # the trading calendar makes the last publicly available report usable
        # until the next disclosure, without moving it before available_at.
        value_panel = (
            group.pivot_table(index="date", columns="instrument", values="value", aggfunc="last")
            .reindex(index=close.index, columns=close.columns)
            .ffill()
        )
        value_panel = value_panel.where(eligible)
        factor_long = value_panel.stack(future_stack=True).rename("value").reset_index().dropna(subset=["value"])
        merged = factor_long.merge(label_long, on=["date", "instrument"], how="left")
        merged["maturity"] = merged["date"].map(maturity_map)
        mature = merged.loc[merged["maturity"].notna() & (merged["maturity"] <= cutoff)].dropna(subset=["value", "label"])
        daily_ic = mature.groupby("date").apply(
            lambda x: x["value"].corr(x["label"], method="spearman") if len(x) >= minimum_cross_section else np.nan,
            include_groups=False,
        ).dropna()
        panels[str(factor_id)] = value_panel.stack(future_stack=True)
        ranks = value_panel.rank(axis=1, pct=True)
        turnover = ranks.diff().abs().mean(axis=1).mean()
        observed = factor_long[["date", "instrument"]].drop_duplicates()
        coverage = len(expected.merge(observed, on=["date", "instrument"])) / max(1, len(expected))
        yearly = daily_ic.groupby(daily_ic.index.year).mean().to_dict() if len(daily_ic) else {}
        latest_label = mature["maturity"].max() if not mature.empty else cutoff
        std = float(daily_ic.std(ddof=1)) if len(daily_ic) > 1 else 0.0
        diagnostic_items.append({
            "factor_id": str(factor_id), "observed_at": cutoff.date().isoformat(),
            "latest_label_date": pd.Timestamp(latest_label).date().isoformat(),
            "observations": int(len(daily_ic)), "coverage": float(min(1.0, coverage)),
            "rank_ic_mean": float(daily_ic.mean()) if len(daily_ic) else 0.0,
            "rank_ic_ir": float(daily_ic.mean() / std) if std > 0 else 0.0,
            "rank_ic_positive_fraction": float((daily_ic > 0).mean()) if len(daily_ic) else 0.0,
            "turnover": float(turnover) if pd.notna(turnover) else 0.0,
            "max_abs_correlation": 0.0,
            "yearly_rank_ic": {str(k): float(v) for k, v in yearly.items()},
            "decay_rank_ic": {str(horizon): float(daily_ic.mean()) if len(daily_ic) else 0.0},
            "warnings": [] if len(daily_ic) >= 24 else ["fewer than 24 matured cross-sectional IC observations"],
        })
    # Redundancy is measured on matching date/instrument observations only.
    for item in diagnostic_items:
        own = panels[item["factor_id"]]
        correlations = [abs(own.corr(other, method="spearman")) for key, other in panels.items() if key != item["factor_id"]]
        valid = [value for value in correlations if pd.notna(value)]
        item["max_abs_correlation"] = float(max(valid, default=0.0))
    registry = {"version": f"aster-factor-registry-{as_of}", "universe": "CSI500_PIT", "factors": registry_items}
    diagnostics = {"label_horizon_days": horizon, "factors": diagnostic_items}
    output_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_root / "factor_registry.json", registry)
    write_json_atomic(output_root / "factor_diagnostics.json", diagnostics)
    return registry, diagnostics


def build_market_context(*, market_path: Path, as_of: str, output_path: Path) -> dict:
    frame = pd.read_parquet(market_path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    cutoff = pd.Timestamp(as_of).normalize()
    frame = frame.loc[frame["date"] <= cutoff]
    stocks = frame.loc[(frame["instrument"] != "SH000905") & frame["csi500_member"].astype(bool)]
    close = stocks.pivot(index="date", columns="instrument", values="close").sort_index()
    benchmark = frame.loc[frame["instrument"] == "SH000905"].set_index("date")["close"].sort_index()
    returns = close.pct_change(fill_method=None)
    corr = returns.tail(60).corr()
    upper = corr.where(np.triu(np.ones(corr.shape), 1).astype(bool)).stack().mean()
    payload = {
        "as_of_close": cutoff.date().isoformat(), "benchmark": "SH000905",
        "benchmark_return_20": float(benchmark.pct_change(20).iloc[-1]),
        "benchmark_return_60": float(benchmark.pct_change(60).iloc[-1]),
        "benchmark_volatility_20": float(benchmark.pct_change().tail(20).std() * np.sqrt(252)),
        "breadth_above_60d_average": float((close.iloc[-1] > close.tail(60).mean()).mean()),
        "cross_section_dispersion_20": float(close.pct_change(20, fill_method=None).iloc[-1].std()),
        "average_pairwise_correlation_60": float(upper),
        "source_ids": ["market:" + sha256_file(market_path)], "limitations": [],
    }
    write_json_atomic(output_path, payload)
    return payload
