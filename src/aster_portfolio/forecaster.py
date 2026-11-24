"""Leakage-aware walk-forward cross-sectional Ridge forecaster."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class ForecastBundle:
    forecasts: dict[pd.Timestamp, pd.Series]
    diagnostics: pd.DataFrame


def _cross_sectional_standardize(frame: pd.DataFrame) -> pd.DataFrame:
    lower = frame.quantile(0.01, axis=1)
    upper = frame.quantile(0.99, axis=1)
    clipped = frame.clip(lower=lower, upper=upper, axis=0)
    mean = clipped.mean(axis=1)
    std = clipped.std(axis=1).replace(0.0, np.nan)
    return clipped.sub(mean, axis=0).div(std, axis=0)


class WalkForwardRidgeForecaster:
    def __init__(
        self,
        *,
        horizon_days: int = 5,
        training_sessions: int = 120,
        alpha: float = 10.0,
        minimum_samples: int = 500,
    ) -> None:
        self.horizon_days = horizon_days
        self.training_sessions = training_sessions
        self.alpha = alpha
        self.minimum_samples = minimum_samples

    def fit_predict(
        self,
        *,
        features: dict[str, pd.DataFrame],
        close: pd.DataFrame,
        signal_dates: list[pd.Timestamp],
        eligibility: pd.DataFrame | None = None,
    ) -> ForecastBundle:
        if not features:
            raise ValueError("at least one feature is required")
        names = sorted(features)
        standardized = {name: _cross_sectional_standardize(features[name]) for name in names}
        for frame in standardized.values():
            if not frame.index.equals(close.index) or not frame.columns.equals(close.columns):
                raise ValueError("feature axes must match close")
        if eligibility is None:
            eligibility = close.notna()
        if not eligibility.index.equals(close.index) or not eligibility.columns.equals(close.columns):
            raise ValueError("eligibility axes must match close")
        eligibility = eligibility.astype(bool)
        forward = close.shift(-self.horizon_days).div(close).sub(1.0)
        labels = forward.sub(forward.mean(axis=1), axis=0)

        forecasts: dict[pd.Timestamp, pd.Series] = {}
        rows: list[dict] = []
        for signal_date in signal_dates:
            signal_date = pd.Timestamp(signal_date)
            if signal_date not in close.index:
                raise ValueError(f"signal date is not in close index: {signal_date}")
            position = close.index.get_loc(signal_date)
            if not isinstance(position, (int, np.integer)):
                raise ValueError("close index must be unique")
            mature_end = int(position) - self.horizon_days
            start = max(0, mature_end - self.training_sessions + 1)
            if mature_end < start:
                continue
            train_dates = close.index[start : mature_end + 1]
            train_columns = []
            for name in names:
                train_columns.append(
                    standardized[name].loc[train_dates].stack(future_stack=True).rename(name)
                )
            train = pd.concat(train_columns, axis=1)
            train["__label__"] = labels.loc[train_dates].stack(future_stack=True)
            train["__eligible__"] = eligibility.loc[train_dates].stack(future_stack=True)
            train = train.replace([np.inf, -np.inf], np.nan)
            feature_values = train[names].fillna(0.0)
            valid = train["__label__"].notna() & train["__eligible__"]
            x = feature_values.loc[valid].to_numpy(dtype=float)
            y = train.loc[valid, "__label__"].to_numpy(dtype=float)
            if len(y) < self.minimum_samples:
                continue
            model = make_pipeline(StandardScaler(), Ridge(alpha=self.alpha, fit_intercept=True))
            model.fit(x, y)

            current = pd.DataFrame(
                {name: standardized[name].loc[signal_date] for name in names},
                index=close.columns,
            ).replace([np.inf, -np.inf], np.nan)
            eligible = close.loc[signal_date].notna() & eligibility.loc[signal_date]
            prediction = pd.Series(np.nan, index=close.columns, dtype=float)
            prediction.loc[eligible] = model.predict(
                current.loc[eligible].fillna(0.0).to_numpy(dtype=float)
            )
            prediction = prediction - prediction.loc[eligible].mean()
            forecasts[signal_date] = prediction
            rows.append(
                {
                    "signal_date": signal_date,
                    "latest_matured_feature_date": train_dates[-1],
                    "training_rows": len(y),
                    "active_features": ",".join(names),
                    "prediction_std": float(prediction.std()),
                }
            )
        return ForecastBundle(forecasts=forecasts, diagnostics=pd.DataFrame(rows))
