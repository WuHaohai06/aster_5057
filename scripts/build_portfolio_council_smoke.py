"""Build a synthetic portfolio-policy Council packet from smoke artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aster_portfolio.council import (
    PortfolioOperatingEvidence,
    build_portfolio_council_packet,
)
from aster_portfolio.schemas import default_profiles
from aster_portfolio.smoke import generate_synthetic_market


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio-smoke-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    market = generate_synthetic_market()
    daily = pd.read_csv(args.portfolio_smoke_root / "daily.csv", parse_dates=["date"]).set_index("date")
    forecast = pd.read_csv(
        args.portfolio_smoke_root / "forecast_diagnostics.csv", parse_dates=["signal_date"]
    )
    as_of = market.close.index[-1]
    benchmark_return_20 = float(market.benchmark_close.iloc[-1] / market.benchmark_close.iloc[-21] - 1)
    benchmark_return_60 = float(market.benchmark_close.iloc[-1] / market.benchmark_close.iloc[-61] - 1)
    benchmark_volatility_20 = float(
        market.benchmark_close.pct_change(fill_method=None).tail(20).std() * (252**0.5)
    )
    breadth = float(
        market.close.iloc[-1].gt(market.close.rolling(60).mean().iloc[-1]).mean()
    )
    current_drawdown = float(daily["nav"].iloc[-1] / daily["nav"].cummax().iloc[-1] - 1)
    realized_volatility = float(daily["return"].tail(20).std() * (252**0.5))
    evidence = PortfolioOperatingEvidence(
        as_of_close=as_of.date(),
        benchmark_return_20=benchmark_return_20,
        benchmark_return_60=benchmark_return_60,
        benchmark_volatility_20=benchmark_volatility_20,
        breadth_above_60d_average=breadth,
        forecast_cross_section_std=float(forecast["prediction_std"].iloc[-1]),
        trailing_rank_ic=None,
        current_drawdown=current_drawdown,
        realized_portfolio_volatility_20=realized_volatility,
        current_estimated_net_beta=float(daily["estimated_net_beta"].iloc[-1]),
        tradable_coverage=1.0,
        recent_one_way_turnover=float(daily["stock_turnover"].tail(20).sum()),
        source_ids=[
            "portfolio:synthetic-smoke:latest",
            "market:synthetic-smoke:latest",
            "forecast:synthetic-smoke:latest",
        ],
        limitations=[
            "All values are synthetic infrastructure-smoke data and are not investment evidence",
            "No matured out-of-sample forecast IC is supplied",
        ],
    )
    profiles = list(default_profiles().values())
    packet = build_portfolio_council_packet(
        decision_at=as_of.date(),
        input_cutoff=as_of.date(),
        evidence=evidence,
        profiles=profiles,
        fallback_profile_id="balanced",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(packet.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
