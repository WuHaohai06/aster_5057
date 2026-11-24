"""Build a point-in-time portfolio Council packet from real replay artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aster_data.io import write_bytes_atomic
from aster_council.schemas import CouncilMode
from aster_portfolio.council import (
    PortfolioOperatingEvidence,
    PortfolioShowcaseDirective,
    build_portfolio_council_packet,
)
from aster_portfolio.schemas import default_profiles


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio-run-root", type=Path, required=True)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--as-of",
        help="Optional evidence cutoff (YYYY-MM-DD); defaults to the replay's last daily row",
    )
    parser.add_argument(
        "--mode", choices=[mode.value for mode in CouncilMode], default=CouncilMode.RESEARCH.value
    )
    parser.add_argument("--showcase-directive", type=Path)
    args = parser.parse_args()
    directive = (
        PortfolioShowcaseDirective.model_validate_json(
            args.showcase_directive.read_text(encoding="utf-8")
        )
        if args.showcase_directive
        else None
    )

    daily_path = args.portfolio_run_root / "daily.csv"
    forecast_path = args.portfolio_run_root / "forecast_diagnostics.csv"
    manifest_path = args.portfolio_run_root / "manifest.json"
    for path in (daily_path, forecast_path, manifest_path, args.market):
        if not path.exists():
            raise FileNotFoundError(path)

    daily = pd.read_csv(daily_path, parse_dates=["date"]).set_index("date").sort_index()
    forecast = pd.read_csv(forecast_path, parse_dates=["signal_date"]).sort_values("signal_date")
    requested_as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else daily.index.max()
    daily = daily.loc[daily.index <= requested_as_of]
    forecast = forecast.loc[forecast["signal_date"] <= requested_as_of]
    if daily.empty or forecast.empty:
        raise ValueError("portfolio artifacts have no point-in-time rows at the requested cutoff")
    as_of = pd.Timestamp(daily.index.max()).normalize()

    market = pd.read_parquet(args.market)
    market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    market = market.loc[market["date"] <= as_of]
    benchmark = (
        market.loc[market["instrument"] == "SH000905", ["date", "close"]]
        .drop_duplicates("date", keep="last")
        .set_index("date")["close"]
        .sort_index()
    )
    if len(benchmark) < 61:
        raise ValueError("fewer than 61 benchmark sessions are available at the cutoff")
    benchmark_as_of = benchmark.index[benchmark.index <= as_of].max()
    if benchmark_as_of != as_of:
        raise ValueError(f"market evidence ends {benchmark_as_of.date()}, replay ends {as_of.date()}")

    stock = market.loc[market["instrument"] != "SH000905"].copy()
    latest = stock.loc[stock["date"] == as_of].set_index("instrument")
    members = latest.index[latest["csi500_member"].astype(bool)]
    if len(members) < 34:
        raise ValueError("fewer than 34 PIT members are available at the cutoff")
    recent_close = (
        stock.loc[stock["instrument"].isin(members), ["date", "instrument", "close"]]
        .pivot(index="date", columns="instrument", values="close")
        .sort_index()
        .tail(60)
    )
    current_close = recent_close.iloc[-1]
    average_60 = recent_close.mean(axis=0, skipna=True)
    breadth_valid = current_close.notna() & average_60.notna()
    breadth = float(current_close.loc[breadth_valid].gt(average_60.loc[breadth_valid]).mean())
    tradable = latest.loc[members, "close"].notna()
    if "volume" in latest:
        tradable &= latest.loc[members, "volume"].fillna(0.0).gt(0.0)

    nav = daily["nav"].astype(float)
    returns = daily["return"].astype(float)
    evidence_ids = [
        f"market:sha256:{_sha256(args.market)}",
        f"portfolio-manifest:sha256:{_sha256(manifest_path)}",
        f"portfolio-daily:sha256:{_sha256(daily_path)}",
        f"forecast-diagnostics:sha256:{_sha256(forecast_path)}",
    ]
    limitations = [
        "The forecaster artifact does not persist per-security matured predictions, so trailing rank IC is unavailable.",
        "The Council may select only a pre-approved deterministic profile; it cannot invent exposures or trades.",
    ]
    market_manifest_path = args.market.parent / "manifest.json"
    if market_manifest_path.exists():
        market_manifest = json.loads(market_manifest_path.read_text(encoding="utf-8"))
        sources = market_manifest.get("rows_by_source", {})
        if any("fallback" in str(key).lower() for key in sources):
            limitations.append(
                "Most canonical equity rows currently use the declared Yahoo adjusted-bar fallback rather than the AKShare primary source."
            )

    evidence = PortfolioOperatingEvidence(
        as_of_close=as_of.date(),
        benchmark_return_20=float(benchmark.iloc[-1] / benchmark.iloc[-21] - 1.0),
        benchmark_return_60=float(benchmark.iloc[-1] / benchmark.iloc[-61] - 1.0),
        benchmark_volatility_20=float(
            benchmark.pct_change(fill_method=None).tail(20).std(ddof=1) * np.sqrt(252)
        ),
        breadth_above_60d_average=breadth,
        forecast_cross_section_std=float(forecast["prediction_std"].iloc[-1]),
        trailing_rank_ic=None,
        current_drawdown=float(nav.iloc[-1] / nav.cummax().iloc[-1] - 1.0),
        realized_portfolio_volatility_20=float(returns.tail(20).std(ddof=1) * np.sqrt(252)),
        current_estimated_net_beta=float(daily["estimated_net_beta"].iloc[-1]),
        tradable_coverage=float(tradable.mean()),
        recent_one_way_turnover=float(daily["stock_turnover"].tail(20).sum()),
        source_ids=evidence_ids,
        limitations=limitations,
    )
    packet = build_portfolio_council_packet(
        decision_at=as_of.date(),
        input_cutoff=as_of.date(),
        evidence=evidence,
        profiles=list(default_profiles().values()),
        fallback_profile_id="balanced",
        mode=CouncilMode(args.mode),
        showcase_directive=directive,
    )
    write_bytes_atomic(args.output, (packet.model_dump_json(indent=2) + "\n").encode("utf-8"))
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "decision_at": as_of.date().isoformat(),
                "packet_digest": packet.packet_digest,
                "mode": packet.mode.value,
                "evidence_ids": evidence_ids,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
