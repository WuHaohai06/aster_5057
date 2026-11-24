"""Joint long-stock and index-futures convex optimizer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import cvxpy as cp
import numpy as np
import pandas as pd

from .schemas import OptimizationDiagnostics, OptimizationResult, PortfolioProfile


@dataclass(frozen=True)
class PortfolioOptimizationInput:
    signal_date: date
    expected_returns: pd.Series
    covariance: pd.DataFrame
    betas: pd.Series
    previous_weights: pd.Series
    previous_futures_short: float
    eligible: pd.Series
    profile: PortfolioProfile
    futures_beta: float = 1.0
    trade_caps: pd.Series | None = None
    turnover_limit: float | None = None


class PortfolioOptimizer:
    def solve(self, data: PortfolioOptimizationInput) -> OptimizationResult:
        names = list(data.expected_returns.index)
        if not names:
            raise ValueError("expected_returns is empty")
        for series_name, series in (
            ("betas", data.betas),
            ("previous_weights", data.previous_weights),
            ("eligible", data.eligible),
        ):
            if set(series.index) != set(names):
                raise ValueError(f"{series_name} index does not match expected_returns")
        covariance = data.covariance.reindex(index=names, columns=names)
        if covariance.isna().any().any():
            raise ValueError("covariance is missing assets")

        mu = data.expected_returns.reindex(names).to_numpy(dtype=float)
        beta = data.betas.reindex(names).to_numpy(dtype=float)
        previous = data.previous_weights.reindex(names).fillna(0.0).to_numpy(dtype=float)
        eligible = data.eligible.reindex(names).astype(bool).to_numpy()
        sigma = covariance.to_numpy(dtype=float)
        if not np.isfinite(mu).all() or not np.isfinite(beta).all() or not np.isfinite(sigma).all():
            raise ValueError("optimizer inputs must be finite")

        profile = data.profile
        legacy_capacity = float(np.minimum(previous[~eligible], profile.name_cap).sum())
        available_capacity = int(eligible.sum()) * profile.name_cap + legacy_capacity
        if available_capacity + 1e-10 < profile.stock_target:
            raise ValueError(
                "eligible and sell-only legacy names cannot fill stock_target "
                f"under name_cap: capacity={available_capacity:.8f}"
            )
        w = cp.Variable(len(names), nonneg=True)
        h = cp.Variable(nonneg=True)
        stock_trade = cp.norm1(w - previous)
        futures_trade = cp.abs(h - float(data.previous_futures_short))
        net_beta = beta @ w - data.futures_beta * h
        objective = cp.Maximize(
            mu @ w
            - profile.risk_aversion * cp.quad_form(w, sigma, assume_PSD=True)
            - profile.stock_trade_cost * stock_trade
            - profile.futures_trade_cost * futures_trade
            - profile.beta_penalty * cp.square(net_beta - profile.target_beta)
        )
        turnover_limit = (
            profile.max_one_way_turnover
            if data.turnover_limit is None
            else float(data.turnover_limit)
        )
        if turnover_limit <= 0:
            raise ValueError("turnover_limit must be positive")
        constraints = [
            w <= profile.name_cap,
            cp.sum(w) == profile.stock_target,
            cp.sum(w) + h <= profile.max_gross,
            net_beta >= profile.target_beta - profile.beta_tolerance,
            net_beta <= profile.target_beta + profile.beta_tolerance,
            profile.futures_margin_rate * h <= 1.0 - cp.sum(w),
            stock_trade <= turnover_limit,
        ]
        if (~eligible).any():
            # A constituent/tradability change can make an immediate full exit
            # incompatible with the profile's hard turnover limit.  Existing
            # positions therefore become sell-only: they may be reduced over
            # several rebalances, but can never be increased.  On the initial
            # build ``previous`` is zero, so ineligible names still receive no
            # allocation at all.
            constraints.append(w[~eligible] <= previous[~eligible])
        if data.trade_caps is not None:
            caps = data.trade_caps.reindex(names).fillna(0.0).to_numpy(dtype=float)
            if (caps < 0).any() or not np.isfinite(caps).all():
                raise ValueError("trade_caps must be finite and nonnegative")
            constraints.extend([w - previous <= caps, previous - w <= caps])

        problem = cp.Problem(objective, constraints)
        last_error: Exception | None = None
        for solver in (cp.CLARABEL, cp.SCS):
            try:
                problem.solve(solver=solver, verbose=False)
            except Exception as error:  # solver-specific failures are retried
                last_error = error
                continue
            if problem.status in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}:
                break
        if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or w.value is None or h.value is None:
            raise RuntimeError(
                "portfolio optimization failed on "
                f"{data.signal_date}: {problem.status}; eligible={int(eligible.sum())}; "
                f"previous_stock_weight={float(previous.sum()):.8f}; "
                f"turnover_limit={turnover_limit:.8f}; {last_error}"
            )

        weights = np.maximum(np.asarray(w.value).reshape(-1), 0.0)
        hedge = max(float(np.asarray(h.value).item()), 0.0)
        stock_weight = float(weights.sum())
        gross = stock_weight + hedge
        estimated_beta = float(beta @ weights - data.futures_beta * hedge)
        cash = 1.0 - stock_weight
        margin = profile.futures_margin_rate * hedge
        turnover = float(np.abs(weights - previous).sum())
        futures_turnover = abs(hedge - float(data.previous_futures_short))
        diagnostics = OptimizationDiagnostics(
            solver_status=str(problem.status),
            objective_value=float(problem.value),
            stock_weight=stock_weight,
            futures_short_weight=hedge,
            gross_exposure=gross,
            estimated_net_beta=estimated_beta,
            cash_weight=cash,
            margin_required=margin,
            one_way_turnover=turnover,
            estimated_stock_cost=profile.stock_trade_cost * turnover,
            estimated_futures_cost=profile.futures_trade_cost * futures_turnover,
            max_name_weight=float(weights.max(initial=0.0)),
            constraint_slack={
                "gross": profile.max_gross - gross,
                "beta_lower": estimated_beta - (profile.target_beta - profile.beta_tolerance),
                "beta_upper": (profile.target_beta + profile.beta_tolerance) - estimated_beta,
                "cash_buffer": cash - profile.cash_buffer,
                "margin_coverage": cash - margin,
                "turnover": turnover_limit - turnover,
                "legacy_ineligible_weight": float(weights[~eligible].sum()),
            },
        )
        return OptimizationResult(
            signal_date=data.signal_date,
            profile_id=profile.profile_id,
            stock_weights={name: float(value) for name, value in zip(names, weights)},
            futures_short_weight=hedge,
            diagnostics=diagnostics,
        )
