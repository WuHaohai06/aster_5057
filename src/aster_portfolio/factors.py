"""Deterministic daily price-volume factor baselines."""

from __future__ import annotations

import numpy as np
import pandas as pd


PRICE_VOLUME_FACTOR_DEFINITIONS = {
    "conventional_momentum": {
        "display_name": "20-day Momentum",
        "expression": "PCT_CHANGE(close, 20)",
        "description": "Twenty-session close-to-close momentum.",
    },
    "conventional_reversal": {
        "display_name": "5-day Reversal",
        "expression": "-PCT_CHANGE(close, 5)",
        "description": "Negative five-session return as a short-horizon reversal signal.",
    },
    "conventional_low_vol": {
        "display_name": "20-day Low Volatility",
        "expression": "-STD(PCT_CHANGE(close, 1), 20)",
        "description": "Negative trailing return volatility.",
    },
    "shock_reversal": {
        "display_name": "Volume-Price Shock Reversal",
        "expression": "-ZSCORE(return,20) * ZSCORE(LOG1P(volume),20)",
        "description": "Interaction between return shock reversal and abnormal volume.",
    },
    "volume_confirmed_momentum": {
        "display_name": "Volume-confirmed Momentum",
        "expression": "PCT_CHANGE(close,20) * ZSCORE(MEAN(LOG1P(volume),5),60)",
        "description": "Twenty-session momentum scaled by the recent volume trend.",
    },
    "close_pressure": {
        "display_name": "Close-location Pressure",
        "expression": "((2*close-high-low)/(high-low)) * ZSCORE(LOG1P(volume),20)",
        "description": "Daily close location interacted with abnormal volume.",
    },
}


def _rolling_zscore(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    mean = frame.rolling(window, min_periods=max(5, window // 2)).mean()
    std = frame.rolling(window, min_periods=max(5, window // 2)).std()
    return (frame - mean) / std.replace(0.0, np.nan)


def compute_price_volume_factors(
    *,
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    if not close.index.equals(high.index) or not close.columns.equals(high.columns):
        raise ValueError("OHLCV panels must have identical axes")
    for frame in (low, volume):
        if not close.index.equals(frame.index) or not close.columns.equals(frame.columns):
            raise ValueError("OHLCV panels must have identical axes")
    returns = close.pct_change(fill_method=None)
    log_volume = np.log1p(volume.where(volume >= 0))
    momentum_20 = close.pct_change(20, fill_method=None)
    reversal_5 = -close.pct_change(5, fill_method=None)
    low_vol_20 = -returns.rolling(20, min_periods=15).std()
    shock_reversal = -_rolling_zscore(returns, 20) * _rolling_zscore(log_volume, 20)
    volume_trend = _rolling_zscore(log_volume.rolling(5, min_periods=3).mean(), 60)
    volume_confirmed_momentum = momentum_20 * volume_trend
    close_location = (2.0 * close - high - low) / (high - low).replace(0.0, np.nan)
    close_pressure = close_location * _rolling_zscore(log_volume, 20)
    return {
        "conventional_momentum": momentum_20,
        "conventional_reversal": reversal_5,
        "conventional_low_vol": low_vol_20,
        "shock_reversal": shock_reversal,
        "volume_confirmed_momentum": volume_confirmed_momentum,
        "close_pressure": close_pressure,
    }
