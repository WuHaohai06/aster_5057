"""Synthetic end-to-end research pipeline for infrastructure validation only."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import BacktestResult, PortfolioBacktester
from .factors import compute_price_volume_factors
from .forecaster import ForecastBundle, WalkForwardRidgeForecaster
from .schemas import default_profiles


@dataclass(frozen=True)
class SyntheticMarket:
    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    benchmark_close: pd.Series
    futures_close: pd.Series


def generate_synthetic_market(
    *, seed: int = 5057, sessions: int = 360, instruments: int = 40
) -> SyntheticMarket:
    if instruments < 27:
        raise ValueError("at least 27 instruments are needed for the 3% cap and 80% profile")
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=sessions)
    names = [f"SH{600000 + index:06d}" for index in range(instruments)]
    market_returns = rng.normal(0.00015, 0.009, sessions)
    betas = rng.uniform(0.65, 1.25, instruments)
    idiosyncratic = rng.normal(0.0, 0.012, (sessions, instruments))
    stock_returns = market_returns[:, None] * betas[None, :] + idiosyncratic
    stock_returns = np.clip(stock_returns, -0.095, 0.095)
    close_values = 50.0 * np.cumprod(1.0 + stock_returns, axis=0)
    close = pd.DataFrame(close_values, index=dates, columns=names)
    daily_range = np.abs(rng.normal(0.012, 0.005, (sessions, instruments)))
    high = close * (1.0 + daily_range / 2.0)
    low = close * (1.0 - daily_range / 2.0)
    log_volume = 15.0 + 8.0 * np.abs(stock_returns) + rng.normal(0.0, 0.45, stock_returns.shape)
    volume = pd.DataFrame(np.exp(log_volume), index=dates, columns=names)
    benchmark_close = pd.Series(
        6000.0 * np.cumprod(1.0 + market_returns), index=dates, name="SH000905"
    )
    futures_returns = market_returns + rng.normal(0.0, 0.0007, sessions)
    futures_close = pd.Series(
        6000.0 * np.cumprod(1.0 + futures_returns), index=dates, name="IC_CONTINUOUS"
    )
    return SyntheticMarket(close, high, low, volume, benchmark_close, futures_close)


def run_synthetic_pipeline(
    profile_id: str = "balanced",
) -> tuple[SyntheticMarket, ForecastBundle, BacktestResult]:
    profiles = default_profiles()
    if profile_id not in profiles:
        raise ValueError(f"unknown approved portfolio profile: {profile_id}")
    market = generate_synthetic_market()
    all_factors = compute_price_volume_factors(
        close=market.close,
        high=market.high,
        low=market.low,
        volume=market.volume,
    )
    active_groups = [
        "conventional_low_vol",
        "shock_reversal",
        "volume_confirmed_momentum",
    ]
    signal_dates = list(market.close.index[180:-2:5])
    forecasts = WalkForwardRidgeForecaster(
        horizon_days=5,
        training_sessions=120,
        alpha=10.0,
        minimum_samples=1000,
    ).fit_predict(
        features={name: all_factors[name] for name in active_groups},
        close=market.close,
        signal_dates=signal_dates,
    )
    result = PortfolioBacktester().run(
        close=market.close,
        volume=market.volume,
        benchmark_close=market.benchmark_close,
        futures_close=market.futures_close,
        forecasts=forecasts.forecasts,
        default_profile=profiles[profile_id],
    )
    return market, forecasts, result


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    # Write exact bytes so manifest hashes are portable across Windows/Unix.
    temporary.write_bytes(content.encode("utf-8"))
    os.replace(temporary, path)


def write_smoke_artifacts(output_root: Path, profile_id: str = "balanced") -> dict:
    market, forecasts, result = run_synthetic_pipeline(profile_id=profile_id)
    output_root.mkdir(parents=True, exist_ok=True)
    optimization_rows = []
    for item in result.optimizations:
        row = {
            "signal_date": item.signal_date.isoformat(),
            "profile_id": item.profile_id,
            **item.diagnostics.model_dump(mode="json"),
        }
        row.pop("constraint_slack")
        row.update({f"slack_{key}": value for key, value in item.diagnostics.constraint_slack.items()})
        optimization_rows.append(row)
    files = {
        "daily.csv": result.daily.to_csv(),
        "target_weights.csv": result.target_weights.to_csv(),
        "forecast_diagnostics.csv": forecasts.diagnostics.to_csv(index=False),
        "optimization_diagnostics.csv": pd.DataFrame(optimization_rows).to_csv(index=False),
        "metrics.json": json.dumps(result.metrics, indent=2, sort_keys=True) + "\n",
    }
    for name, content in files.items():
        _write_atomic(output_root / name, content)
    manifest = {
        "dataset": "synthetic-infrastructure-smoke-only",
        "profile_id": profile_id,
        "sessions": len(market.close),
        "instruments": len(market.close.columns),
        "forecasts": len(forecasts.forecasts),
        "optimizations": len(result.optimizations),
        "files": {
            name: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for name, content in files.items()
        },
    }
    _write_atomic(output_root / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {**manifest, "metrics": result.metrics, "output_root": str(output_root.resolve())}
