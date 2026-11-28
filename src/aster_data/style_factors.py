"""Deterministic market-ready style factors for the PIT CSI500 universe."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .factor_store import FACTOR_COLUMNS
from .io import sha256_file, write_json_atomic


STYLE_FACTOR_DEFINITIONS: dict[str, dict[str, Any]] = {
    "beta_shrunk_252": {
        "display_name": "Shrunk Rolling Beta",
        "group": "style_beta",
        "family": "beta",
        "expression": "-(0.6 * beta_252 + 0.4)",
        "description": "Negative 252-session market beta shrunk toward one.",
        "hypothesis": "Reliably estimated lower-beta stocks earn stronger subsequent risk-adjusted returns.",
        "mechanism": "Leverage constraints and lottery demand can overprice high-beta stocks; shrinkage reduces estimation noise.",
        "direction": "higher means lower shrunk beta",
    },
    "beta_downside_asymmetry": {
        "display_name": "Downside Beta Asymmetry",
        "group": "style_beta",
        "family": "beta",
        "expression": "-(beta_down_120 - beta_up_120)",
        "description": "Difference between down-market and up-market beta.",
        "hypothesis": "Stocks with disproportionate downside beta subsequently underperform otherwise similar stocks.",
        "mechanism": "Down-market covariance captures funding and forced-selling exposure hidden by unconditional beta.",
        "direction": "higher means less downside-beta asymmetry",
    },
    "beta_instability": {
        "display_name": "Beta Stability",
        "group": "style_beta",
        "family": "beta",
        "expression": "-(abs(beta_60-beta_252)+std(beta_60,120))",
        "description": "Penalty for disagreement and instability in rolling beta.",
        "hypothesis": "Unstable systematic exposure predicts weaker subsequent performance.",
        "mechanism": "Changing beta can proxy for business-model uncertainty, leverage changes or transient crowding.",
        "direction": "higher means more stable beta",
    },
    "momentum_rank_persistence": {
        "display_name": "Rank Momentum Persistence",
        "group": "style_momentum",
        "family": "momentum",
        "expression": "mean(cs_rank(return),120,skip_recent=20)",
        "description": "Average daily cross-sectional return rank with a recent-period skip.",
        "hypothesis": "Persistent relative return rank is more robust than momentum dominated by a few outliers.",
        "mechanism": "Gradual information diffusion creates persistent ordering across the stock universe.",
        "direction": "higher persistent rank predicts higher return",
    },
    "momentum_market_residual": {
        "display_name": "Market Residual Momentum",
        "group": "style_momentum",
        "family": "momentum",
        "expression": "sum(return-beta_252_lag*benchmark_return,120,skip_recent=20)",
        "description": "Medium-horizon momentum after removing lagged benchmark beta.",
        "hypothesis": "Firm-specific residual momentum persists more reliably than benchmark-driven momentum.",
        "mechanism": "Removing market returns isolates gradual incorporation of firm-specific information.",
        "direction": "higher residual momentum predicts higher return",
    },
    "momentum_path_quality": {
        "display_name": "Momentum Path Quality",
        "group": "style_momentum",
        "family": "momentum",
        "expression": "sum(return,120)*abs(sum(return,120))/sum(abs(return),120),skip_recent=20",
        "description": "Signed momentum weighted by the smoothness of its return path.",
        "hypothesis": "Smooth trends are more likely to persist than jump-dominated cumulative returns.",
        "mechanism": "Smooth price paths are consistent with gradual information absorption rather than temporary attention shocks.",
        "direction": "higher means smoother positive momentum",
    },
    "residual_volatility_idiosyncratic": {
        "display_name": "Idiosyncratic Volatility",
        "group": "style_residual_volatility",
        "family": "residual_volatility",
        "expression": "-std(return-beta_252_lag*benchmark_return,60)",
        "description": "Negative volatility of market-residual daily returns.",
        "hypothesis": "Lower idiosyncratic volatility predicts stronger subsequent risk-adjusted performance.",
        "mechanism": "Lottery preference and limits to arbitrage can overprice high-idiosyncratic-volatility stocks.",
        "direction": "higher means lower idiosyncratic volatility",
    },
    "residual_volatility_downside": {
        "display_name": "Residual Downside Volatility",
        "group": "style_residual_volatility",
        "family": "residual_volatility",
        "expression": "-sqrt(mean(min(residual_return,0)^2,120))",
        "description": "Negative downside semideviation of market-residual returns.",
        "hypothesis": "Residual downside variation identifies firm-specific fragility more directly than symmetric volatility.",
        "mechanism": "Negative residual shocks reveal forced-selling exposure and unresolved firm-specific risk.",
        "direction": "higher means lower residual downside volatility",
    },
    "residual_volatility_of_volatility": {
        "display_name": "Residual Volatility Stability",
        "group": "style_residual_volatility",
        "family": "residual_volatility",
        "expression": "-std(rolling_std(residual_return,20),120)",
        "description": "Negative volatility of rolling idiosyncratic volatility.",
        "hypothesis": "Unstable idiosyncratic volatility is adverse beyond its average level.",
        "mechanism": "Volatility-of-volatility captures changing information uncertainty and intermittent liquidity stress.",
        "direction": "higher means more stable residual volatility",
    },
    "liquidity_relative_volume_impact": {
        "display_name": "Relative-Volume Price Impact",
        "group": "style_liquidity",
        "family": "liquidity",
        "expression": "-mean(abs(return)/(volume/median(volume,60)+0.1),20)",
        "description": "Price impact scaled by volume relative to the stock's own history.",
        "hypothesis": "Large price changes on weak own-history volume indicate shallow liquidity.",
        "mechanism": "Limited participation allows temporary order imbalance to move prices more strongly.",
        "direction": "higher means lower relative-volume price impact",
    },
    "liquidity_low_volume_persistence": {
        "display_name": "Low-Volume Persistence",
        "group": "style_liquidity",
        "family": "liquidity",
        "expression": "-mean(volume<rolling_quantile(volume,60,0.2),20)",
        "description": "Negative fraction of recent sessions with unusually low own-history volume.",
        "hypothesis": "Persistent low participation predicts weaker tradability and less reliable apparent alpha.",
        "mechanism": "Attention scarcity increases trading frictions and implementation risk.",
        "direction": "higher means less persistent low-volume trading",
    },
    "liquidity_volume_instability": {
        "display_name": "Volume Stability",
        "group": "style_liquidity",
        "family": "liquidity",
        "expression": "-std(delta(log(volume+1)),60)",
        "description": "Negative volatility of changes in log trading volume.",
        "hypothesis": "Unstable participation signals event dependence and less dependable liquidity.",
        "mechanism": "Large changes in trading activity proxy for intermittent attention and liquidity provision.",
        "direction": "higher means more stable trading participation",
    },
}


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _pivot(frame: pd.DataFrame, column: str, instruments: list[str]) -> pd.DataFrame:
    return (
        frame.loc[frame["instrument"].isin(instruments)]
        .pivot(index="date", columns="instrument", values=column)
        .sort_index()
        .reindex(columns=instruments)
    )


def _rolling_beta(
    returns: pd.DataFrame, benchmark: pd.Series, window: int, minimum: int
) -> pd.DataFrame:
    covariance = returns.rolling(window, min_periods=minimum).cov(benchmark)
    variance = benchmark.rolling(window, min_periods=minimum).var()
    return covariance.div(variance.replace(0.0, np.nan), axis=0)


def compute_style_panels(market: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    frame = market.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    members = frame.loc[
        (frame["instrument"] != "SH000905") & frame["csi500_member"].astype(bool)
    ]
    instruments = sorted(members["instrument"].unique())
    close = _pivot(frame, "close", instruments)
    volume = _pivot(frame, "volume", instruments).where(lambda value: value > 0)
    eligibility = (
        frame.loc[frame["instrument"].isin(instruments)]
        .pivot(index="date", columns="instrument", values="csi500_member")
        .sort_index()
        .reindex(index=close.index, columns=instruments)
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    )
    benchmark = (
        frame.loc[frame["instrument"] == "SH000905"]
        .set_index("date")["close"]
        .sort_index()
        .reindex(close.index)
    )
    returns = close.pct_change(fill_method=None)
    benchmark_returns = benchmark.pct_change(fill_method=None)

    beta_252 = _rolling_beta(returns, benchmark_returns, 252, 126)
    beta_60 = _rolling_beta(returns, benchmark_returns, 60, 30)
    down_benchmark = benchmark_returns.where(benchmark_returns < 0)
    up_benchmark = benchmark_returns.where(benchmark_returns > 0)
    beta_down = _rolling_beta(returns.where(benchmark_returns < 0, axis=0), down_benchmark, 120, 25)
    beta_up = _rolling_beta(returns.where(benchmark_returns > 0, axis=0), up_benchmark, 120, 25)

    lagged_beta = beta_252.shift(1)
    residual = returns.sub(lagged_beta.mul(benchmark_returns, axis=0))
    skipped_returns = returns.shift(20)
    skipped_residual = residual.shift(20)
    daily_rank = returns.where(eligibility).rank(axis=1, pct=True).sub(0.5)
    trend = skipped_returns.rolling(120, min_periods=60).sum()
    path_length = skipped_returns.abs().rolling(120, min_periods=60).sum()

    relative_volume = volume.div(volume.rolling(60, min_periods=30).median())
    low_volume = volume.lt(volume.rolling(60, min_periods=30).quantile(0.2)).where(
        volume.rolling(60, min_periods=30).count().ge(30)
    )
    log_volume_change = np.log1p(volume).diff()

    panels = {
        "beta_shrunk_252": -(0.6 * beta_252 + 0.4),
        "beta_downside_asymmetry": -(beta_down - beta_up),
        "beta_instability": -(
            (beta_60 - beta_252).abs()
            + beta_60.rolling(120, min_periods=60).std()
        ),
        "momentum_rank_persistence": daily_rank.shift(20).rolling(120, min_periods=60).mean(),
        "momentum_market_residual": skipped_residual.rolling(120, min_periods=60).sum(),
        "momentum_path_quality": trend * trend.abs() / path_length.replace(0.0, np.nan),
        "residual_volatility_idiosyncratic": -residual.rolling(60, min_periods=30).std(),
        "residual_volatility_downside": -np.sqrt(
            residual.clip(upper=0).pow(2).rolling(120, min_periods=30).mean()
        ),
        "residual_volatility_of_volatility": -(
            residual.rolling(20, min_periods=10).std().rolling(120, min_periods=60).std()
        ),
        "liquidity_relative_volume_impact": -(
            returns.abs().div(relative_volume.add(0.1)).rolling(20, min_periods=10).mean()
        ),
        "liquidity_low_volume_persistence": -low_volume.astype(float).rolling(
            20, min_periods=10
        ).mean(),
        "liquidity_volume_instability": -log_volume_change.rolling(60, min_periods=30).std(),
    }
    return {
        factor_id: panel.replace([np.inf, -np.inf], np.nan).where(eligibility)
        for factor_id, panel in panels.items()
    }, eligibility


def build_style_factors(
    *, market_path: Path, output_root: Path, sample_every: int = 5
) -> dict[str, Any]:
    if sample_every < 1:
        raise ValueError("sample_every must be positive")
    market = pd.read_parquet(market_path)
    panels, _ = compute_style_panels(market)
    rows = []
    source_digest = sha256_file(market_path)
    for factor_id, panel in panels.items():
        sampled = panel.iloc[::sample_every]
        long = sampled.stack(future_stack=True).rename("value").reset_index()
        long = long.dropna(subset=["value"])
        definition = STYLE_FACTOR_DEFINITIONS[factor_id]
        long["available_at"] = long["date"]
        long["factor_id"] = factor_id
        long["factor_group"] = definition["group"]
        long["origin"] = "aster_style_factors"
        long["source_id"] = f"market:{source_digest}:style:{factor_id}"
        long["version"] = "aster-style-factors-v1"
        rows.append(long[FACTOR_COLUMNS])
    result = pd.concat(rows, ignore_index=True).sort_values(
        ["date", "instrument", "factor_id"]
    )
    output = output_root / "style_factors.parquet"
    _write_parquet_atomic(result, output)
    manifest = {
        "dataset": "aster-style-factors-v1",
        "rows": int(len(result)),
        "instruments": int(result["instrument"].nunique()),
        "factor_ids": sorted(result["factor_id"].unique()),
        "groups": sorted(result["factor_group"].unique()),
        "sample_every": sample_every,
        "market_sha256": source_digest,
        "path": str(output.resolve()),
        "sha256": sha256_file(output),
    }
    write_json_atomic(output_root / "style_factors_manifest.json", manifest)
    return manifest
