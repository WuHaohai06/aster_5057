"""Run Aster's deterministic research chain on canonical real-data artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from aster_council.schemas import CouncilDecision
from aster_data.factor_library import LifecycleStatus, load_catalog, load_factor_values
from aster_data.io import sha256_file, write_bytes_atomic, write_json_atomic

from .backtest import PortfolioBacktester
from .council import PortfolioCouncilDecision
from .factors import compute_price_volume_factors
from .forecaster import WalkForwardRidgeForecaster
from .schemas import approved_profiles, default_profiles


DEFAULT_GROUPS = [
    "conventional_momentum",
    "conventional_reversal",
    "conventional_low_vol",
]


def _pivot(frame: pd.DataFrame, column: str, instruments: list[str]) -> pd.DataFrame:
    return (
        frame.pivot(index="date", columns="instrument", values=column)
        .sort_index()
        .reindex(columns=instruments)
    )


def _selected_groups(
    path: Path | None, *, replay_start: pd.Timestamp
) -> tuple[list[str], dict | None]:
    if path is None:
        return DEFAULT_GROUPS, None
    raw = path.read_bytes()
    decision = CouncilDecision.model_validate_json(raw)
    if pd.Timestamp(decision.input_cutoff) > replay_start:
        raise ValueError("Factor Council decision contains information after replay start")
    return decision.selected_groups, {
        "run_id": decision.run_id,
        "packet_digest": decision.packet_digest,
        "decision_sha256": hashlib.sha256(raw).hexdigest(),
        "fallback_used": decision.fallback_used,
        "mode": decision.mode.value,
        "uses_hindsight": decision.uses_hindsight,
        "disclosure": decision.disclosure,
    }


def _selected_profile(
    path: Path | None, *, replay_start: pd.Timestamp, replay_end: pd.Timestamp
) -> tuple[str, str, pd.Timestamp | None, pd.Timestamp | None, dict | None]:
    if path is None:
        return "balanced", "balanced", None, None, None
    raw = path.read_bytes()
    decision = PortfolioCouncilDecision.model_validate_json(raw)
    if pd.Timestamp(decision.input_cutoff) > replay_end:
        raise ValueError("Portfolio Council decision contains information after replay end")
    if decision.selected_profile_id not in approved_profiles():
        raise ValueError("Portfolio Council selected an unknown approved profile")
    if decision.uses_hindsight:
        effective_start = pd.Timestamp(decision.showcase_future_window_start)
        effective_end = pd.Timestamp(decision.showcase_future_window_end)
    else:
        effective_start = pd.Timestamp(decision.input_cutoff) + pd.Timedelta(days=1)
        effective_end = None
    default_profile_id = (
        "balanced"
        if decision.uses_hindsight
        else (decision.selected_profile_id if effective_start <= replay_start else "balanced")
    )
    return default_profile_id, decision.selected_profile_id, effective_start, effective_end, {
        "run_id": decision.run_id,
        "packet_digest": decision.packet_digest,
        "decision_sha256": hashlib.sha256(raw).hexdigest(),
        "fallback_used": decision.fallback_used,
        "mode": decision.mode.value,
        "uses_hindsight": decision.uses_hindsight,
        "effective_start": effective_start.date().isoformat(),
        "effective_end": effective_end.date().isoformat() if effective_end is not None else None,
        "industry_overweights": decision.industry_overweights,
        "industry_underweights": decision.industry_underweights,
        "industry_active_tilt": decision.industry_active_tilt,
    }


def _resolve_factor_features(
    *,
    groups: list[str],
    builtins: dict[str, pd.DataFrame],
    catalog_path: Path | None,
    project_root: Path,
    dates: pd.DatetimeIndex,
    instruments: list[str],
) -> tuple[dict[str, pd.DataFrame], dict | None, dict[str, list[str]]]:
    features: dict[str, pd.DataFrame] = {}
    feature_ids_by_group: dict[str, list[str]] = {}
    external_groups = []
    for group in groups:
        if group in builtins:
            features[group] = builtins[group]
            feature_ids_by_group[group] = [group]
        else:
            external_groups.append(group)
    if not external_groups:
        if catalog_path is None:
            return features, None, feature_ids_by_group
        catalog = load_catalog(catalog_path)
        return features, {
            "path": str(catalog_path.resolve()),
            "sha256": sha256_file(catalog_path),
            "catalog_digest": catalog.catalog_digest,
            "external_factor_ids": [],
        }, feature_ids_by_group
    if catalog_path is None:
        raise ValueError(f"factor groups require a catalog: {sorted(external_groups)}")
    catalog = load_catalog(catalog_path)
    external_ids = []
    for group in external_groups:
        records = [
            item for item in catalog.factors
            if item.lifecycle_status != LifecycleStatus.RETIRED
            and (item.factor_group == group or item.factor_id == group)
        ]
        if not records:
            raise ValueError(f"factor catalog has no active factor for group: {group}")
        for record in records:
            values = load_factor_values(
                project_root=project_root,
                catalog_path=catalog_path,
                factor_id=record.factor_id,
            )
            values["date"] = pd.to_datetime(values["date"]).dt.normalize()
            values["available_at"] = pd.to_datetime(values["available_at"]).dt.normalize()
            if (values["available_at"] > values["date"]).any():
                raise ValueError(f"factor {record.factor_id} violates available_at <= date")
            signal_timestamp = values[["date", "available_at"]].max(axis=1)
            positions = dates.searchsorted(pd.DatetimeIndex(signal_timestamp), side="left")
            valid_positions = positions < len(dates)
            values = values.loc[valid_positions].copy()
            values["signal_date"] = dates.take(positions[valid_positions])
            panel = (
                values.pivot_table(
                    index="signal_date", columns="instrument", values="value", aggfunc="last"
                )
                .reindex(index=dates, columns=instruments)
                .ffill()
            )
            features[record.factor_id] = panel
            external_ids.append(record.factor_id)
            feature_ids_by_group.setdefault(group, []).append(record.factor_id)
    return features, {
        "path": str(catalog_path.resolve()),
        "sha256": sha256_file(catalog_path),
        "catalog_digest": catalog.catalog_digest,
        "external_factor_ids": external_ids,
    }, feature_ids_by_group


def _load_factor_schedule(path: Path | None) -> tuple[list[dict], dict | None]:
    if path is None:
        return [], None
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schema") != "aster-factor-schedule-v1":
        raise ValueError("unknown factor schedule schema")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("factor schedule must contain at least one entry")
    normalised = []
    for item in entries:
        selected = item.get("selected_groups")
        if not isinstance(selected, list) or not selected or len(selected) != len(set(selected)):
            raise ValueError("each factor schedule entry needs unique selected_groups")
        effective_from = pd.Timestamp(item["effective_from"]).normalize()
        effective_to = (
            pd.Timestamp(item["effective_to"]).normalize() if item.get("effective_to") else None
        )
        input_cutoff = pd.Timestamp(item["input_cutoff"]).normalize()
        if input_cutoff >= effective_from and not item.get("uses_hindsight", False):
            raise ValueError("research schedule input_cutoff must precede effective_from")
        if effective_to is not None and effective_to < effective_from:
            raise ValueError("factor schedule effective_to precedes effective_from")
        normalised.append({
            **item,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "input_cutoff": input_cutoff,
        })
    normalised.sort(key=lambda item: item["effective_from"])
    return normalised, {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload["schema"],
        "session_id": payload.get("session_id"),
    }


def _groups_for_signal(signal_date: pd.Timestamp, schedule: list[dict]) -> list[str]:
    selected = DEFAULT_GROUPS
    for entry in schedule:
        if signal_date < entry["effective_from"]:
            continue
        if entry["effective_to"] is not None and signal_date > entry["effective_to"]:
            continue
        selected = entry["selected_groups"]
    return selected


def _load_portfolio_schedule(path: Path | None) -> tuple[list[dict], dict | None]:
    if path is None:
        return [], None
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schema") != "aster-portfolio-schedule-v1":
        raise ValueError("unknown portfolio schedule schema")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("portfolio schedule must contain at least one entry")
    approved = approved_profiles()
    normalised = []
    for item in entries:
        profile_id = item.get("selected_profile_id")
        if profile_id not in approved:
            raise ValueError("portfolio schedule selected an unknown approved profile")
        effective_from = pd.Timestamp(item["effective_from"]).normalize()
        effective_to = (
            pd.Timestamp(item["effective_to"]).normalize() if item.get("effective_to") else None
        )
        input_cutoff = pd.Timestamp(item["input_cutoff"]).normalize()
        if input_cutoff >= effective_from and not item.get("uses_hindsight", False):
            raise ValueError("research portfolio input_cutoff must precede effective_from")
        if effective_to is not None and effective_to < effective_from:
            raise ValueError("portfolio schedule effective_to precedes effective_from")
        overweights = item.get("industry_overweights", [])
        underweights = item.get("industry_underweights", [])
        active_tilt = float(item.get("industry_active_tilt", 0.0))
        if not isinstance(overweights, list) or not isinstance(underweights, list):
            raise ValueError("portfolio industry selections must be lists")
        if len(overweights) > 3 or len(underweights) > 3:
            raise ValueError("portfolio schedule allows at most three industries per side")
        if set(overweights).intersection(underweights):
            raise ValueError("an industry cannot be both overweight and underweight")
        if active_tilt not in {0.0, 0.05, 0.08, 0.10, 0.15, 0.20}:
            raise ValueError("portfolio schedule active tilt is not an approved level")
        if (overweights or underweights) and active_tilt == 0.0:
            raise ValueError("portfolio industry selections require a positive active tilt")
        normalised.append({
            **item,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "input_cutoff": input_cutoff,
            "industry_overweights": overweights,
            "industry_underweights": underweights,
            "industry_active_tilt": active_tilt,
        })
    normalised.sort(key=lambda item: item["effective_from"])
    return normalised, {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload["schema"],
        "session_id": payload.get("session_id"),
    }


def _portfolio_policy_for_signal(signal_date: pd.Timestamp, schedule: list[dict]) -> dict | None:
    selected = None
    for entry in schedule:
        if signal_date < entry["effective_from"]:
            continue
        if entry["effective_to"] is not None and signal_date > entry["effective_to"]:
            continue
        selected = entry
    return selected


def run_real_pipeline(
    *,
    market_path: Path,
    futures_path: Path,
    output_root: Path,
    start: str,
    end: str,
    factor_decision_path: Path | None = None,
    factor_schedule_path: Path | None = None,
    portfolio_decision_path: Path | None = None,
    portfolio_schedule_path: Path | None = None,
    factor_catalog_path: Path | None = None,
    industry_snapshot_path: Path | None = None,
    industry_benchmark_path: Path | None = None,
    horizon_days: int = 20,
    training_sessions: int = 504,
    rebalance_every: int = 5,
    allow_incomplete_ic: bool = False,
) -> dict:
    market = pd.read_parquet(market_path)
    required = {
        "date",
        "instrument",
        "high",
        "low",
        "close",
        "volume",
        "csi500_member",
    }
    missing = required.difference(market.columns)
    if missing:
        raise ValueError(f"canonical market data is missing: {sorted(missing)}")
    market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    market = market.loc[market["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    benchmark_rows = market.loc[market["instrument"] == "SH000905"].copy()
    if benchmark_rows.empty:
        raise ValueError("canonical market data has no SH000905 benchmark")
    benchmark = benchmark_rows.set_index("date")["close"].sort_index()
    stock_rows = market.loc[
        (market["instrument"] != "SH000905") & market["csi500_member"].astype(bool)
    ].copy()
    instruments = sorted(stock_rows["instrument"].unique())
    if len(instruments) < 34:
        raise ValueError("fewer than 34 PIT-eligible instruments cannot satisfy the 3% cap")
    all_stock_rows = market.loc[market["instrument"].isin(instruments)].copy()
    close = _pivot(all_stock_rows, "close", instruments)
    high = _pivot(all_stock_rows, "high", instruments)
    low = _pivot(all_stock_rows, "low", instruments)
    volume = _pivot(all_stock_rows, "volume", instruments)
    eligibility = (
        all_stock_rows.pivot(index="date", columns="instrument", values="csi500_member")
        .sort_index()
        .reindex(index=close.index, columns=instruments)
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    )
    futures_manifest_path = futures_path.parent / "manifest.json"
    if futures_manifest_path.exists() and not allow_incomplete_ic:
        futures_manifest = json.loads(futures_manifest_path.read_text(encoding="utf-8"))
        if futures_manifest.get("missing_months"):
            raise ValueError("IC manifest has missing monthly archives")
    futures = pd.read_parquet(futures_path)
    futures["date"] = pd.to_datetime(futures["date"]).dt.normalize()
    futures = futures.set_index("date").sort_index()
    if "nav_index" not in futures:
        raise ValueError("IC continuous data must contain the same-contract nav_index")
    common = close.index.intersection(benchmark.index).intersection(futures.index)
    common = common[(common >= pd.Timestamp(start)) & (common <= pd.Timestamp(end))]
    if len(common) < training_sessions + horizon_days + 20:
        raise ValueError("real-data overlap is too short for the requested walk-forward setup")
    close, high, low, volume, eligibility = (
        frame.reindex(common) for frame in (close, high, low, volume, eligibility)
    )
    benchmark = benchmark.reindex(common)
    futures_close = futures["nav_index"].reindex(common)
    if factor_decision_path is not None and factor_schedule_path is not None:
        raise ValueError("use factor_decision_path or factor_schedule_path, not both")
    schedule, factor_schedule_link = _load_factor_schedule(factor_schedule_path)
    groups, factor_link = _selected_groups(factor_decision_path, replay_start=pd.Timestamp(start))
    if schedule:
        groups = sorted(
            set(DEFAULT_GROUPS).union(
                group for entry in schedule for group in entry["selected_groups"]
            )
        )
    factors = compute_price_volume_factors(
        close=close, high=high, low=low, volume=volume
    )
    project_root = Path(__file__).resolve().parents[2]
    feature_panels, factor_catalog_link, feature_ids_by_group = _resolve_factor_features(
        groups=groups,
        builtins=factors,
        catalog_path=factor_catalog_path,
        project_root=project_root,
        dates=common,
        instruments=instruments,
    )
    first_signal = training_sessions + horizon_days
    signal_dates = list(common[first_signal : -horizon_days : rebalance_every])
    feature_names_by_signal = None
    if schedule:
        feature_names_by_signal = {
            signal_date: [
                feature_id
                for group in _groups_for_signal(signal_date, schedule)
                for feature_id in feature_ids_by_group[group]
            ]
            for signal_date in signal_dates
        }
    forecasts = WalkForwardRidgeForecaster(
        horizon_days=horizon_days,
        training_sessions=training_sessions,
        alpha=10.0,
        minimum_samples=5000,
    ).fit_predict(
        features=feature_panels,
        close=close,
        signal_dates=signal_dates,
        eligibility=eligibility,
        feature_names_by_signal=feature_names_by_signal,
    )
    if portfolio_decision_path is not None and portfolio_schedule_path is not None:
        raise ValueError("use portfolio_decision_path or portfolio_schedule_path, not both")
    portfolio_schedule, portfolio_schedule_link = _load_portfolio_schedule(
        portfolio_schedule_path
    )
    default_profile_id, selected_profile_id, effective_start, effective_end, portfolio_link = _selected_profile(
        portfolio_decision_path,
        replay_start=pd.Timestamp(start),
        replay_end=pd.Timestamp(end),
    )
    profile_by_signal = {}
    industry_policy_by_signal: dict[pd.Timestamp, dict] = {}
    industries = None
    industry_benchmark_weights = None
    if portfolio_schedule:
        default_profile_id = "balanced"
        selected_profile_id = portfolio_schedule[-1]["selected_profile_id"]
        profile_by_signal = {
            signal_date: approved_profiles()[policy["selected_profile_id"]]
            for signal_date in forecasts.forecasts
            if (policy := _portfolio_policy_for_signal(signal_date, portfolio_schedule))
            is not None
        }
        industry_policy_by_signal = {
            signal_date: {
                "overweights": policy["industry_overweights"],
                "underweights": policy["industry_underweights"],
                "active_tilt": policy["industry_active_tilt"],
            }
            for signal_date in forecasts.forecasts
            if (policy := _portfolio_policy_for_signal(signal_date, portfolio_schedule))
            is not None
            and policy["industry_active_tilt"] > 0.0
        }
        if industry_policy_by_signal:
            if industry_snapshot_path is None or industry_benchmark_path is None:
                raise ValueError("industry Council schedule requires snapshot and benchmark inputs")
            snapshot = pd.read_parquet(industry_snapshot_path)
            industries = snapshot.set_index("instrument")["industry_name"].reindex(instruments)
            benchmark_industry = pd.read_parquet(industry_benchmark_path)
            benchmark_industry["date"] = pd.to_datetime(
                benchmark_industry["date"]
            ).dt.normalize()
            industry_benchmark_weights = (
                benchmark_industry.pivot(
                    index="date", columns="industry_name", values="benchmark_weight"
                )
                .sort_index()
                .fillna(0.0)
            )
    elif effective_start is not None:
        selected_profile = approved_profiles()[selected_profile_id]
        profile_by_signal = {
            signal_date: selected_profile
            for signal_date in forecasts.forecasts
            if signal_date >= effective_start
            and (effective_end is None or signal_date <= effective_end)
        }
        if portfolio_link and portfolio_link["industry_active_tilt"] > 0.0:
            if industry_snapshot_path is None or industry_benchmark_path is None:
                raise ValueError("industry Council decision requires snapshot and benchmark inputs")
            snapshot = pd.read_parquet(industry_snapshot_path)
            industries = snapshot.set_index("instrument")["industry_name"].reindex(instruments)
            benchmark_industry = pd.read_parquet(industry_benchmark_path)
            benchmark_industry["date"] = pd.to_datetime(benchmark_industry["date"]).dt.normalize()
            industry_benchmark_weights = (
                benchmark_industry.pivot(
                    index="date", columns="industry_name", values="benchmark_weight"
                )
                .sort_index()
                .fillna(0.0)
            )
            policy = {
                "overweights": portfolio_link["industry_overweights"],
                "underweights": portfolio_link["industry_underweights"],
                "active_tilt": portfolio_link["industry_active_tilt"],
            }
            industry_policy_by_signal = {
                signal_date: policy
                for signal_date in forecasts.forecasts
                if signal_date >= effective_start
                and (effective_end is None or signal_date <= effective_end)
            }
    result = PortfolioBacktester().run(
        close=close,
        volume=volume,
        benchmark_close=benchmark,
        futures_close=futures_close,
        forecasts=forecasts.forecasts,
        default_profile=approved_profiles()[default_profile_id],
        profile_by_signal=profile_by_signal,
        industries=industries,
        industry_benchmark_weights=industry_benchmark_weights,
        industry_policy_by_signal=industry_policy_by_signal,
        eligibility=eligibility,
        risk_window=252,
        risk_horizon_days=5,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    optimization_rows = []
    for item in result.optimizations:
        row = {
            "signal_date": item.signal_date.isoformat(),
            "profile_id": item.profile_id,
            **item.diagnostics.model_dump(mode="json"),
        }
        row.pop("constraint_slack")
        row.update(
            {f"slack_{key}": value for key, value in item.diagnostics.constraint_slack.items()}
        )
        optimization_rows.append(row)
    text_files = {
        "daily.csv": result.daily.to_csv(lineterminator="\n"),
        "target_weights.csv": result.target_weights.to_csv(lineterminator="\n"),
        "forecast_diagnostics.csv": forecasts.diagnostics.to_csv(
            index=False, lineterminator="\n"
        ),
        "optimization_diagnostics.csv": pd.DataFrame(optimization_rows).to_csv(
            index=False, lineterminator="\n"
        ),
        "metrics.json": json.dumps(result.metrics, indent=2, sort_keys=True) + "\n",
    }
    for name, content in text_files.items():
        write_bytes_atomic(output_root / name, content.encode("utf-8"))
    manifest = {
        "dataset": "aster-real-data-replay-v1",
        "start": start,
        "end": end,
        "sessions": len(common),
        "instruments": len(instruments),
        "factor_groups": groups,
        "factor_features": sorted(feature_panels),
        "profile_id": default_profile_id,
        "selected_profile_id": selected_profile_id,
        "profile_override_signals": len(profile_by_signal),
        "industry_override_signals": len(industry_policy_by_signal),
        "horizon_days": horizon_days,
        "training_sessions": training_sessions,
        "rebalance_every": rebalance_every,
        "forecasts": len(forecasts.forecasts),
        "optimizations": len(result.optimizations),
        "factor_council": factor_link,
        "factor_schedule": factor_schedule_link,
        "factor_schedule_entries": [
            {
                **entry,
                "effective_from": entry["effective_from"].date().isoformat(),
                "effective_to": (
                    entry["effective_to"].date().isoformat()
                    if entry["effective_to"] is not None else None
                ),
                "input_cutoff": entry["input_cutoff"].date().isoformat(),
            }
            for entry in schedule
        ],
        "factor_catalog": factor_catalog_link,
        "portfolio_council": portfolio_link,
        "portfolio_schedule": portfolio_schedule_link,
        "portfolio_schedule_entries": [
            {
                **entry,
                "effective_from": entry["effective_from"].date().isoformat(),
                "effective_to": (
                    entry["effective_to"].date().isoformat()
                    if entry["effective_to"] is not None else None
                ),
                "input_cutoff": entry["input_cutoff"].date().isoformat(),
            }
            for entry in portfolio_schedule
        ],
        "inputs": {
            "market": {"path": str(market_path.resolve()), "sha256": sha256_file(market_path)},
            "ic_futures": {
                "path": str(futures_path.resolve()),
                "sha256": sha256_file(futures_path),
            },
            "industry_snapshot": (
                {"path": str(industry_snapshot_path.resolve()), "sha256": sha256_file(industry_snapshot_path)}
                if industry_snapshot_path is not None else None
            ),
            "industry_benchmark": (
                {"path": str(industry_benchmark_path.resolve()), "sha256": sha256_file(industry_benchmark_path)}
                if industry_benchmark_path is not None else None
            ),
        },
        "files": {
            name: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for name, content in text_files.items()
        },
        "metrics": result.metrics,
    }
    write_json_atomic(output_root / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--ic-futures", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--factor-decision", type=Path)
    parser.add_argument("--factor-schedule", type=Path)
    parser.add_argument("--portfolio-decision", type=Path)
    parser.add_argument("--portfolio-schedule", type=Path)
    parser.add_argument("--factor-catalog", type=Path)
    parser.add_argument("--industry-snapshot", type=Path)
    parser.add_argument("--industry-benchmark", type=Path)
    parser.add_argument("--horizon-days", type=int, default=20)
    parser.add_argument("--training-sessions", type=int, default=504)
    parser.add_argument("--rebalance-every", type=int, default=5)
    parser.add_argument("--allow-incomplete-ic", action="store_true")
    args = parser.parse_args()
    result = run_real_pipeline(
        market_path=args.market,
        futures_path=args.ic_futures,
        output_root=args.output_root,
        start=args.start,
        end=args.end,
        factor_decision_path=args.factor_decision,
        factor_schedule_path=args.factor_schedule,
        portfolio_decision_path=args.portfolio_decision,
        portfolio_schedule_path=args.portfolio_schedule,
        factor_catalog_path=args.factor_catalog,
        industry_snapshot_path=args.industry_snapshot,
        industry_benchmark_path=args.industry_benchmark,
        horizon_days=args.horizon_days,
        training_sessions=args.training_sessions,
        rebalance_every=args.rebalance_every,
        allow_incomplete_ic=args.allow_incomplete_ic,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
