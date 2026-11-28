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
    stock_matrix = values.to_numpy(dtype=float, copy=False)

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
        imputed_mask = valid_counts.to_numpy() < minimum_observations
        reliable = np.flatnonzero(~imputed_mask)
        reference_variance = (
            float(np.nanmedian(np.diag(covariance)[reliable])) if len(reliable) else 1e-4
        )
        reference_variance = max(reference_variance, 1e-8)
        covariance[imputed_mask, :] = 0.0
        covariance[:, imputed_mask] = 0.0
        covariance[imputed_mask, imputed_mask] = reference_variance * 2.0
    # A convex combination of a sample covariance and its non-negative
    # diagonal is already positive semidefinite.  Repeating a full O(N^3)
    # eigen decomposition for every rebalance added substantial latency at
    # CSI500 scale.  Symmetrise for floating-point noise and floor only truly
    # degenerate diagonal entries; cvxpy receives the matrix with assume_PSD.
    covariance = (covariance + covariance.T) / 2.0
    floor = max(float(np.nanmedian(np.diag(covariance))) * 1e-8, 1e-12)
    diagonal_positions = np.diag_indices_from(covariance)
    covariance[diagonal_positions] = np.maximum(covariance[diagonal_positions], floor)

    benchmark = aligned["__benchmark__"].to_numpy(dtype=float, copy=False)
    benchmark_variance = float(np.nanvar(benchmark, ddof=1))
    if not np.isfinite(benchmark_variance) or benchmark_variance <= 0:
        raise ValueError("benchmark variance is not positive")
    # Pairwise covariance with the benchmark, vectorised across all assets.
    # This is algebraically equivalent to the former per-column DataFrame
    # dropna/cov loop, but avoids thousands of temporary frames per replay.
    valid = np.isfinite(stock_matrix) & np.isfinite(benchmark)[:, None]
    counts = valid.sum(axis=0)
    x = np.where(valid, stock_matrix, 0.0)
    y = np.where(valid, benchmark[:, None], 0.0)
    sum_x = x.sum(axis=0)
    sum_y = y.sum(axis=0)
    covariance_numerator = (x * y).sum(axis=0) - sum_x * sum_y / np.maximum(counts, 1)
    pair_covariance = covariance_numerator / np.maximum(counts - 1, 1)
    beta_values = np.where(
        counts >= minimum_observations,
        pair_covariance / benchmark_variance,
        1.0,
    )

    return RiskEstimate(
        covariance=pd.DataFrame(covariance, index=stocks, columns=stocks),
        betas=pd.Series(beta_values, index=stocks, dtype=float),
        observations=len(aligned),
        imputed_assets=tuple(imputed),
    )
