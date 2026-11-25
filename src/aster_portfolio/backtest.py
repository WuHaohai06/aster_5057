"""One-close-lag portfolio replay with deterministic costs and risk estimates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .optimizer import PortfolioOptimizationInput, PortfolioOptimizer
from .risk import estimate_risk
from .schemas import OptimizationResult, PortfolioProfile


@dataclass(frozen=True)
class BacktestResult:
    daily: pd.DataFrame
    target_weights: pd.DataFrame
    optimizations: list[OptimizationResult]
    metrics: dict[str, float]


def performance_metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = daily["return"].dropna()
    if returns.empty:
        return {}
    annual_return = float(daily["nav"].iloc[-1] ** (252 / len(returns)) - 1)
    annual_volatility = float(returns.std(ddof=1) * np.sqrt(252))
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) > 0 else 0.0
    drawdown = daily["nav"].div(daily["nav"].cummax()).sub(1.0)
    return {
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "total_stock_turnover": float(daily["stock_turnover"].sum()),
        "total_futures_turnover": float(daily["futures_turnover"].sum()),
        "total_cost_fraction": float(daily["cost_fraction"].sum()),
        "mean_gross_exposure": float(daily["gross_exposure"].mean()),
        "max_abs_estimated_beta": float(daily["estimated_net_beta"].abs().max()),
    }


class PortfolioBacktester:
    def __init__(self, optimizer: PortfolioOptimizer | None = None) -> None:
        self.optimizer = optimizer or PortfolioOptimizer()

    def run(
        self,
        *,
        close: pd.DataFrame,
        volume: pd.DataFrame,
        benchmark_close: pd.Series,
        futures_close: pd.Series,
        forecasts: dict[pd.Timestamp, pd.Series],
        default_profile: PortfolioProfile,
        profile_by_signal: dict[pd.Timestamp, PortfolioProfile] | None = None,
        industries: pd.Series | None = None,
        industry_benchmark_weights: pd.DataFrame | None = None,
        industry_policy_by_signal: dict[pd.Timestamp, dict] | None = None,
        eligibility: pd.DataFrame | None = None,
        risk_window: int = 120,
        risk_horizon_days: int = 5,
    ) -> BacktestResult:
        index = close.index
        if not index.equals(volume.index) or not close.columns.equals(volume.columns):
            raise ValueError("close and volume axes must match")
        if eligibility is None:
            eligibility = close.notna() & volume.fillna(0.0).gt(0.0)
        if not eligibility.index.equals(index) or not eligibility.columns.equals(close.columns):
            raise ValueError("eligibility axes must match close")
        eligibility = eligibility.astype(bool)
        benchmark_close = benchmark_close.reindex(index)
        futures_close = futures_close.reindex(index)
        if benchmark_close.isna().any() or futures_close.isna().any():
            raise ValueError("benchmark/futures history must cover the replay index")
        stock_returns = close.pct_change(fill_method=None)
        benchmark_returns = benchmark_close.pct_change(fill_method=None)
        futures_returns = futures_close.pct_change(fill_method=None)
        profile_by_signal = profile_by_signal or {}
        industry_policy_by_signal = industry_policy_by_signal or {}
        if industries is not None:
            industries = industries.reindex(close.columns).fillna("Unknown").astype(str)
        if industry_benchmark_weights is not None:
            industry_benchmark_weights = industry_benchmark_weights.sort_index()
        forecast_map = {pd.Timestamp(key): value for key, value in forecasts.items()}

        weights = pd.Series(0.0, index=close.columns)
        futures_short = 0.0
        nav = 1.0
        daily_rows: list[dict] = []
        target_rows: list[pd.Series] = []
        optimizations: list[OptimizationResult] = []
        last_estimated_beta = 0.0
        last_industry_policy: tuple[tuple[str, ...], tuple[str, ...], float] = ((), (), 0.0)

        for position in range(1, len(index)):
            current_date = index[position]
            signal_date = index[position - 1]
            stock_day = stock_returns.loc[current_date].fillna(0.0)
            futures_day = float(futures_returns.loc[current_date])
            stock_contribution = float(weights @ stock_day)
            futures_contribution = -futures_short * futures_day
            gross_return = float(stock_contribution + futures_contribution)
            nav *= 1.0 + gross_return
            denominator = 1.0 + gross_return
            if denominator <= 0:
                raise RuntimeError("portfolio NAV became non-positive")
            weights = weights.mul(1.0 + stock_day).div(denominator)
            futures_short = futures_short * (1.0 + futures_day) / denominator

            stock_turnover = 0.0
            futures_turnover = 0.0
            cost_fraction = 0.0
            rebalanced = False
            profile_id = ""
            industry_overweights: tuple[str, ...] = ()
            industry_underweights: tuple[str, ...] = ()
            industry_active_tilt = 0.0
            if signal_date in forecast_map:
                profile = profile_by_signal.get(signal_date, default_profile)
                industry_policy = industry_policy_by_signal.get(signal_date, {})
                industry_overweights = tuple(industry_policy.get("overweights", ()))
                industry_underweights = tuple(industry_policy.get("underweights", ()))
                industry_active_tilt = float(industry_policy.get("active_tilt", 0.0))
                industry_signature = (
                    industry_overweights,
                    industry_underweights,
                    industry_active_tilt,
                )
                industry_policy_changed = industry_signature != last_industry_policy
                benchmark_industry = None
                if industry_benchmark_weights is not None:
                    eligible_dates = industry_benchmark_weights.index[
                        industry_benchmark_weights.index <= signal_date
                    ]
                    if len(eligible_dates):
                        benchmark_industry = industry_benchmark_weights.loc[eligible_dates[-1]]
                expected = forecast_map[signal_date].reindex(close.columns)
                eligible = (
                    close.loc[signal_date].notna()
                    & volume.loc[signal_date].fillna(0.0).gt(0.0)
                    & expected.notna()
                    & eligibility.loc[signal_date]
                )
                history = stock_returns.loc[:signal_date]
                risk = estimate_risk(
                    history,
                    benchmark_returns.loc[:signal_date],
                    window=risk_window,
                    horizon_days=risk_horizon_days,
                    shrinkage=profile.covariance_shrinkage,
                )
                initial_build = float(weights.sum()) < 1e-8
                result = self.optimizer.solve(
                    PortfolioOptimizationInput(
                        signal_date=signal_date.date(),
                        expected_returns=expected.fillna(0.0),
                        covariance=risk.covariance,
                        betas=risk.betas,
                        previous_weights=weights,
                        previous_futures_short=futures_short,
                        eligible=eligible,
                        profile=profile,
                        turnover_limit=(
                            profile.stock_target
                            if initial_build
                            else 1.0
                            if industry_policy_changed
                            else max(
                                profile.max_one_way_turnover,
                                min(1.0, 2.0 * industry_active_tilt * len(industry_overweights)),
                            )
                        ),
                        industries=industries,
                        industry_benchmark_weights=benchmark_industry,
                        industry_overweights=industry_overweights,
                        industry_underweights=industry_underweights,
                        industry_active_tilt=industry_active_tilt,
                    )
                )
                target = pd.Series(result.stock_weights).reindex(close.columns).fillna(0.0)
                stock_turnover = float((target - weights).abs().sum())
                futures_turnover = abs(result.futures_short_weight - futures_short)
                cost_fraction = (
                    profile.stock_trade_cost * stock_turnover
                    + profile.futures_trade_cost * futures_turnover
                )
                if cost_fraction >= 1.0:
                    raise RuntimeError("transaction costs consumed the portfolio")
                nav *= 1.0 - cost_fraction
                weights = target
                futures_short = result.futures_short_weight
                last_estimated_beta = result.diagnostics.estimated_net_beta
                profile_id = profile.profile_id
                last_industry_policy = industry_signature
                optimizations.append(result)
                target.name = current_date
                target_rows.append(target)
                rebalanced = True

            daily_rows.append(
                {
                    "date": current_date,
                    "nav": nav,
                    "return": (1.0 + gross_return) * (1.0 - cost_fraction) - 1.0,
                    "stock_return": stock_contribution,
                    "futures_return_contribution": futures_contribution,
                    "stock_weight": float(weights.sum()),
                    "futures_short_weight": futures_short,
                    "gross_exposure": float(weights.sum() + futures_short),
                    "estimated_net_beta": last_estimated_beta,
                    "stock_turnover": stock_turnover,
                    "futures_turnover": futures_turnover,
                    "cost_fraction": cost_fraction,
                    "rebalanced": rebalanced,
                    "signal_date": signal_date if rebalanced else pd.NaT,
                    "profile_id": profile_id,
                    "industry_overweights": ",".join(industry_overweights),
                    "industry_underweights": ",".join(industry_underweights),
                    "industry_active_tilt": industry_active_tilt,
                }
            )

        daily = pd.DataFrame(daily_rows).set_index("date")
        targets = pd.DataFrame(target_rows).fillna(0.0)
        return BacktestResult(
            daily=daily,
            target_weights=targets,
            optimizations=optimizations,
            metrics=performance_metrics(daily),
        )
