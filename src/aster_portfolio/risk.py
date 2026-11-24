"""Point-in-time shrinkage covariance and market-beta estimation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RiskEstimate:
    covariance: pd.DataFrame
    betas: pd.Series
    observations: int
    imputed_assets: tuple[str, ...] = ()


def estimate_risk(
    stock_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    *,
    window: int = 120,
    horizon_days: int = 5,
    shrinkage: float = 0.25,
    minimum_observations: int = 60,
) -> RiskEstimate:
    if not 0.0 <= shrinkage <= 1.0:
        raise ValueError("shrinkage must be in [0, 1]")
    aligned = stock_returns.join(benchmark_returns.rename("__benchmark__"), how="inner").tail(window)
    aligned = aligned.replace([np.inf, -np.inf], np.nan)
    if len(aligned) < minimum_observations:
        raise ValueError(f"risk history has {len(aligned)} rows; need {minimum_observations}")
    stocks = list(stock_returns.columns)
    values = aligned[stocks].copy()
    valid_counts = values.notna().sum()
    imputed = valid_counts[valid_counts < minimum_observations].index.tolist()

    # Missing daily returns are neutralized only after demeaning each series;
    # eligibility/tradability is handled separately by the optimizer.
    demeaned = values - values.mean(axis=0)
    matrix = demeaned.fillna(0.0).to_numpy(dtype=float)
    sample = np.cov(matrix, rowvar=False, ddof=1)
    sample = np.atleast_2d(sample)
    diagonal = np.diag(np.diag(sample))
    covariance = (1.0 - shrinkage) * sample + shrinkage * diagonal
    covariance *= horizon_days
    if imputed:
        reliable = [stocks.index(name) for name in stocks if name not in imputed]
        reference_variance = (
            float(np.nanmedian(np.diag(covariance)[reliable])) if reliable else 1e-4
        )
        reference_variance = max(reference_variance, 1e-8)
        for name in imputed:
            position = stocks.index(name)
            covariance[position, :] = 0.0
            covariance[:, position] = 0.0
            covariance[position, position] = reference_variance * 2.0
    eigenvalues, eigenvectors = np.linalg.eigh((covariance + covariance.T) / 2.0)
    floor = max(float(np.nanmedian(np.diag(covariance))) * 1e-8, 1e-12)
    covariance = eigenvectors @ np.diag(np.maximum(eigenvalues, floor)) @ eigenvectors.T

    benchmark = aligned["__benchmark__"]
    benchmark_variance = float(benchmark.var(ddof=1))
    if not np.isfinite(benchmark_variance) or benchmark_variance <= 0:
        raise ValueError("benchmark variance is not positive")
    betas = {}
    for column in stocks:
        pair = aligned[[column, "__benchmark__"]].dropna()
        if len(pair) < minimum_observations:
            betas[column] = 1.0
        else:
            betas[column] = float(pair[column].cov(pair["__benchmark__"]) / benchmark_variance)

    return RiskEstimate(
        covariance=pd.DataFrame(covariance, index=stocks, columns=stocks),
        betas=pd.Series(betas, dtype=float),
        observations=len(aligned),
        imputed_assets=tuple(imputed),
    )
