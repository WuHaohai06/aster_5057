"""Audited human-in-the-loop Factor Council replay sessions."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from aster_council.schemas import (
    SHOWCASE_DISCLOSURE,
    ChairRecommendation,
    CouncilDecision,
    CouncilMode,
    DecisionPacket,
)
from aster_council.llm import DeepSeekCouncilClient, StructuredLLM
from aster_council.validation import validate_recommendation
from aster_data.io import write_json_atomic
from aster_portfolio.council import (
    RESEARCH_PROMPT as PORTFOLIO_RESEARCH_PROMPT,
    SHOWCASE_PROMPT as PORTFOLIO_SHOWCASE_PROMPT,
    IndustryOperatingEvidence,
    PortfolioChairRecommendation,
    PortfolioOperatingEvidence,
    PortfolioShowcaseDirective,
    build_portfolio_council_packet,
    validate_portfolio_recommendation,
)
from aster_portfolio.schemas import approved_profiles, default_profiles

from .web_research import DeepSeekWebResearchCollector


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSION_ROOT = PROJECT_ROOT / "run" / "aster_console" / "replay_sessions"
COUNCIL_ROOTS = (
    PROJECT_ROOT / "data" / "council" / "filing_ai_showcase_runs",
    PROJECT_ROOT / "data" / "council" / "showcase_runs",
    PROJECT_ROOT / "data" / "council" / "real_runs",
)
DEFAULT_REPLAY_END = "2026-11-23"
MARKET_PATH = PROJECT_ROOT / "data" / "curated" / "market" / "daily.parquet"
INDUSTRY_SNAPSHOT_PATH = (
    PROJECT_ROOT / "data" / "curated" / "industry_snapshot" / "latest.parquet"
)
INDUSTRY_BENCHMARK_PATH = (
    PROJECT_ROOT / "data" / "curated" / "industry_snapshot" / "benchmark_weights.parquet"
)
FACTOR_PROMPT_VERSION = "aster-replay-factor-agenda-v2"
PORTFOLIO_PROMPT_VERSION = "aster-replay-portfolio-agenda-v1"


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_packet(path: Path) -> DecisionPacket:
    """Load current packets and preserve read compatibility with early v1 artifacts."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    for group in payload.get("factor_groups", []):
        for factor in group.get("factors", []):
            factor.setdefault("formula", f"legacy-formula-sha256:{factor.get('formula_hash', 'unknown')}")
    return DecisionPacket.model_validate(payload)


def _node_evidence_age_days(node: dict[str, Any]) -> int:
    stored = node.get("evidence_age_days")
    if isinstance(stored, int):
        return stored
    try:
        return max(
            0,
            (
                date.fromisoformat(str(node.get("decision_at")))
                - date.fromisoformat(str(node.get("evidence_as_of")))
            ).days,
        )
    except (TypeError, ValueError):
        return 0


def _evidence_health(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise how fresh the Factor Council evidence is for each quarter."""

    statuses: list[str] = []
    stale: list[dict[str, Any]] = []
    for node in nodes:
        age = _node_evidence_age_days(node)
        statuses.append("current" if age == 0 else "carry_forward")
        # A showcase reenactment intentionally reuses one disclosed scenario
        # packet; only research-mode quarters are expected to refresh quarterly.
        if age > 92 and node.get("mode") != "showcase_reenactment":
            stale.append(node)
    as_of = [node["evidence_as_of"] for node in nodes if node.get("evidence_as_of")]
    warnings: list[str] = []
    if stale:
        quarters = ", ".join(node["node_id"].replace("factor-council-", "") for node in stale[:4])
        warnings.append(
            f"{len(stale)} of {len(nodes)} quarters carry evidence older than one quarter "
            f"({quarters}); refresh the Factor Council evidence chain before judging performance."
        )
    return {
        "current": statuses.count("current"),
        "carry_forward": statuses.count("carry_forward"),
        "stale": len(stale),
        "oldest_evidence_as_of": min(as_of) if as_of else None,
        "latest_evidence_as_of": max(as_of) if as_of else None,
        "warnings": warnings,
    }


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    public = json.loads(json.dumps(session))
    public["evidence_health"] = _evidence_health(public.get("nodes", []))
    for node in public["nodes"]:
        node.pop("packet_path", None)
        node.pop("decision_path", None)
        node.pop("packet_payload", None)
        node.pop("portfolio_packet_payload", None)
        for round_item in node["rounds"]:
            round_item.pop("raw_text", None)
        for round_item in node.get("portfolio_rounds", []):
            round_item.pop("raw_text", None)
    return public


def _interactive_packet(packet: DecisionPacket) -> dict[str, Any]:
    """Keep the evidence needed for deliberation without resending large yearly tables."""
    return {
        "decision_at": packet.decision_at.isoformat(),
        "input_cutoff": packet.input_cutoff.isoformat(),
        "mode": packet.mode.value,
        "packet_digest": packet.packet_digest,
        "market": packet.market.model_dump(mode="json"),
        "constraints": packet.constraints.model_dump(mode="json"),
        "evidence_ids": packet.evidence_ids,
        "factor_groups": [
            {
                "group_id": group.group_id,
                "coverage_min": group.coverage_min,
                "rank_ic_mean_median": group.rank_ic_mean_median,
                "rank_ic_ir_median": group.rank_ic_ir_median,
                "turnover_median": group.turnover_median,
                "max_abs_correlation": group.max_abs_correlation,
                "warnings": group.warnings,
                "factors": [
                    {
                        "factor_id": factor.factor_id,
                        "description": factor.description,
                        "economic_hypothesis": factor.economic_hypothesis,
                        "mechanism_explanation": factor.mechanism_explanation,
                        "expected_direction": factor.expected_direction,
                        "falsification_criteria": factor.falsification_criteria,
                        "coverage": factor.coverage,
                        "rank_ic_mean": factor.rank_ic_mean,
                        "rank_ic_ir": factor.rank_ic_ir,
                        "turnover": factor.turnover,
                        "max_abs_correlation": factor.max_abs_correlation,
                        "warnings": factor.warnings,
                        "evidence_id": factor.evidence_id,
                    }
                    for factor in group.factors
                ],
            }
            for group in packet.factor_groups
        ],
    }


class ReplayService:
    def __init__(
        self,
        *,
        session_root: Path = SESSION_ROOT,
        client_factory: Callable[[], StructuredLLM] | None = None,
        web_collector_factory: Callable[[], Any] | None = None,
        launch_runs: bool = True,
    ) -> None:
        self.session_root = session_root
        self.client_factory = client_factory or (lambda: DeepSeekCouncilClient(max_tokens=20000))
        self.web_collector_factory = web_collector_factory or DeepSeekWebResearchCollector
        self.web_search_enabled = os.environ.get("ASTER_COUNCIL_WEB_SEARCH", "1") != "0"
        self.launch_runs = launch_runs
        self._lock = threading.RLock()
        self._market_cache: pd.DataFrame | None = None
        self._industry_cache: pd.DataFrame | None = None
        self._industry_benchmark_cache: pd.DataFrame | None = None

    @staticmethod
    def _initial_portfolio_round(round_id: str = "round-0") -> dict[str, Any]:
        profile = default_profiles()["balanced"]
        return {
            "round_id": round_id,
            "factor_round_id": round_id,
            "origin": "deterministic_initial_policy",
            "created_at": _now(),
            "selected_profile_id": profile.profile_id,
            "stock_target": profile.stock_target,
            "target_beta": profile.target_beta,
            "beta_tolerance": profile.beta_tolerance,
            "industry_overweights": [],
            "industry_underweights": [],
            "industry_active_tilt": 0.0,
            "rationale": (
                "Initial bounded policy uses the approved balanced profile and remains industry "
                "neutral until the second-stage Portfolio Agenda is deliberated."
            ),
            "evidence_ids": [],
            "dissent": [],
            "confidence": 0.0,
            "fallback_used": True,
            "fallback_reason": "Portfolio Agenda has not yet been rerun for this replay node.",
            "valid": True,
            "validation_errors": [],
            "model": "deterministic-policy",
            "prompt_hash": PORTFOLIO_PROMPT_VERSION,
            "token_usage": None,
            "packet_digest": None,
            "raw_text": None,
        }

    def _market_inputs(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if self._market_cache is None:
            if not MARKET_PATH.exists():
                raise FileNotFoundError(MARKET_PATH)
            market = pd.read_parquet(
                MARKET_PATH,
                columns=["date", "instrument", "close", "volume", "csi500_member"],
            )
            market["date"] = pd.to_datetime(market["date"]).dt.normalize()
            self._market_cache = market
        if self._industry_cache is None:
            if not INDUSTRY_SNAPSHOT_PATH.exists():
                raise FileNotFoundError(INDUSTRY_SNAPSHOT_PATH)
            snapshot = pd.read_parquet(INDUSTRY_SNAPSHOT_PATH)
            snapshot["snapshot_date"] = pd.to_datetime(snapshot["snapshot_date"]).dt.normalize()
            self._industry_cache = snapshot
        if self._industry_benchmark_cache is None:
            if not INDUSTRY_BENCHMARK_PATH.exists():
                raise FileNotFoundError(INDUSTRY_BENCHMARK_PATH)
            benchmark = pd.read_parquet(INDUSTRY_BENCHMARK_PATH)
            benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.normalize()
            self._industry_benchmark_cache = benchmark
        return self._market_cache, self._industry_cache, self._industry_benchmark_cache

    def _portfolio_packet(
        self,
        *,
        node: dict[str, Any],
        factor_packet: DecisionPacket,
        factor_round: dict[str, Any],
        web_evidence: dict[str, Any],
    ):
        market, snapshot, benchmark_industry = self._market_inputs()
        cutoff = pd.Timestamp(node["input_cutoff"]).normalize()
        available = market.loc[market["date"] <= cutoff]
        if available.empty:
            raise ValueError("no market observations are available by the Portfolio Agenda cutoff")
        as_of = available["date"].max()
        latest = available.loc[available["date"].eq(as_of)]
        members = latest.loc[
            (latest["instrument"] != "SH000905") & latest["csi500_member"].astype(bool),
            "instrument",
        ].astype(str)
        benchmark = (
            available.loc[available["instrument"].eq("SH000905"), ["date", "close"]]
            .drop_duplicates("date", keep="last")
            .set_index("date")["close"]
            .sort_index()
        )
        stock_close = (
            available.loc[available["instrument"].isin(members), ["date", "instrument", "close"]]
            .pivot(index="date", columns="instrument", values="close")
            .sort_index()
        )
        recent = stock_close.tail(60)
        breadth_valid = recent.iloc[-1].notna() & recent.mean().notna()
        breadth = float(
            recent.iloc[-1].loc[breadth_valid].gt(recent.mean().loc[breadth_valid]).mean()
        )
        latest_members = latest.set_index("instrument").reindex(members)
        tradable = latest_members["close"].notna() & latest_members["volume"].fillna(0).gt(0)

        selected = set(factor_round["selected_groups"])
        selected_groups = [group for group in factor_packet.factor_groups if group.group_id in selected]
        factor_rank_ics = [factor.rank_ic_mean for group in selected_groups for factor in group.factors]
        selected_turnover = [group.turnover_median for group in selected_groups]
        selected_coverage = [group.coverage_min for group in selected_groups]
        source_ids = set(factor_round.get("evidence_ids", []))
        source_ids.update(factor_packet.market.source_ids)
        source_ids.update(
            item["evidence_id"] for item in web_evidence.get("accepted", [])
        )
        factor_round_evidence_id = f"factor-agenda:sha256:{_digest(factor_round)}"
        source_ids.add(factor_round_evidence_id)

        snapshot_date = snapshot["snapshot_date"].max()
        uses_future_snapshot = snapshot_date > as_of
        mapping = snapshot.drop_duplicates("instrument", keep="last").set_index("instrument")[
            "industry_name"
        ].astype(str)
        industry_weights = benchmark_industry.loc[benchmark_industry["date"] <= as_of]
        latest_weight_date = industry_weights["date"].max() if not industry_weights.empty else None
        latest_weights = (
            industry_weights.loc[industry_weights["date"].eq(latest_weight_date)]
            .set_index("industry_name")["benchmark_weight"]
            if latest_weight_date is not None
            else pd.Series(dtype=float)
        )
        industry_evidence: list[IndustryOperatingEvidence] = []
        for industry, names_index in pd.Series(members).groupby(
            pd.Series(members).map(mapping).fillna("Unknown")
        ):
            names = list(names_index.astype(str))
            if industry == "Unknown" or len(names) < 5 or industry not in latest_weights.index:
                continue
            panel = stock_close.reindex(columns=names).dropna(how="all")
            if len(panel) < 61:
                continue
            return_20 = panel.iloc[-1].div(panel.iloc[-21]).sub(1).mean()
            return_60 = panel.iloc[-1].div(panel.iloc[-61]).sub(1).mean()
            returns = panel.pct_change(fill_method=None).mean(axis=1)
            average_60 = panel.tail(60).mean()
            valid = panel.iloc[-1].notna() & average_60.notna()
            industry_evidence.append(
                IndustryOperatingEvidence(
                    industry_name=str(industry),
                    benchmark_weight=float(latest_weights.loc[industry]),
                    member_count=len(names),
                    return_20=float(return_20),
                    return_60=float(return_60),
                    volatility_20=float(returns.tail(20).std(ddof=1) * np.sqrt(252)),
                    breadth_above_60d_average=float(
                        panel.iloc[-1].loc[valid].gt(average_60.loc[valid]).mean()
                    ),
                    evidence_id=f"industry:{industry}:asof:{as_of.date().isoformat()}",
                )
            )

        benchmark_return = benchmark.pct_change(fill_method=None)
        benchmark_drawdown = benchmark.div(benchmark.cummax()).sub(1.0)
        limitations = [
            "Portfolio Agenda follows the Factor Agenda and may not change factor formulas or selected groups.",
            "Before the segment backtest, benchmark volatility proxies realized portfolio volatility.",
            "Forecast dispersion is proxied by dispersion in matured selected-factor rank IC values.",
        ]
        if uses_future_snapshot:
            limitations.append(
                "Industry labels use a static snapshot dated after this cutoff; research-mode decisions must remain industry neutral."
            )
        evidence = PortfolioOperatingEvidence(
            as_of_close=as_of.date(),
            benchmark_return_20=float(benchmark.iloc[-1] / benchmark.iloc[-21] - 1.0),
            benchmark_return_60=float(benchmark.iloc[-1] / benchmark.iloc[-61] - 1.0),
            benchmark_volatility_20=float(benchmark_return.tail(20).std(ddof=1) * np.sqrt(252)),
            breadth_above_60d_average=breadth,
            forecast_cross_section_std=float(np.std(factor_rank_ics)) if factor_rank_ics else 0.0,
            trailing_rank_ic=float(np.median(factor_rank_ics)) if factor_rank_ics else None,
            current_drawdown=float(benchmark_drawdown.iloc[-1]),
            realized_portfolio_volatility_20=float(
                benchmark_return.tail(20).std(ddof=1) * np.sqrt(252)
            ),
            current_estimated_net_beta=0.0,
            tradable_coverage=float(tradable.mean()),
            recent_one_way_turnover=float(np.median(selected_turnover)) if selected_turnover else 0.0,
            industries=industry_evidence,
            industry_snapshot_date=snapshot_date.date(),
            industry_snapshot_uses_future_information=uses_future_snapshot,
            source_ids=sorted(source_ids),
            limitations=limitations,
        )

        mode = CouncilMode(node["mode"])
        directive = None
        if mode == CouncilMode.SHOWCASE_REENACTMENT:
            future_start = pd.Timestamp(node["segment_start"]).normalize()
            future_end = pd.Timestamp(node["segment_end"]).normalize()
            future_market = market.loc[market["date"].between(future_start, future_end)]
            future_benchmark = (
                future_market.loc[future_market["instrument"].eq("SH000905"), ["date", "close"]]
                .drop_duplicates("date", keep="last")
                .set_index("date")["close"]
                .sort_index()
            )
            future_return = (
                float(future_benchmark.iloc[-1] / future_benchmark.iloc[0] - 1.0)
                if len(future_benchmark) >= 2
                else 0.0
            )
            target_profile = (
                "defensive" if future_return <= -0.03
                else "opportunistic" if future_return >= 0.03
                else "balanced"
            )
            future_stocks = future_market.loc[future_market["instrument"].isin(members)].copy()
            future_stocks["industry_name"] = future_stocks["instrument"].map(mapping)
            allowed_industries = {item.industry_name for item in industry_evidence}
            future_stocks = future_stocks.loc[
                future_stocks["industry_name"].isin(allowed_industries)
            ]
            industry_returns: dict[str, float] = {}
            for industry, frame in future_stocks.dropna(subset=["industry_name"]).groupby(
                "industry_name"
            ):
                panel = frame.pivot(index="date", columns="instrument", values="close").sort_index()
                if panel.shape[0] >= 2 and panel.shape[1] >= 5:
                    industry_returns[str(industry)] = float(
                        panel.iloc[-1].div(panel.iloc[0]).sub(1.0).mean()
                    )
            ranked = sorted(industry_returns, key=industry_returns.get)
            underweights = ranked[:2] if len(ranked) >= 4 else []
            overweights = ranked[-2:] if len(ranked) >= 4 else []
            directive = PortfolioShowcaseDirective(
                target_profile_id=target_profile,
                target_industry_overweights=overweights,
                target_industry_underweights=underweights,
                target_industry_active_tilt=0.10 if overweights and underweights else 0.0,
                future_window_start=future_start.date(),
                future_window_end=future_end.date(),
                retrospective_outcome_summary=(
                    f"Hindsight selected the {target_profile} profile for a course-demo segment "
                    f"whose later CSI 500 return was {future_return:.2%}."
                ),
                disclosure=SHOWCASE_DISCLOSURE,
            )
        profiles = list(
            (approved_profiles() if mode == CouncilMode.SHOWCASE_REENACTMENT else default_profiles()).values()
        )
        packet = build_portfolio_council_packet(
            decision_at=date.fromisoformat(node["decision_at"]),
            input_cutoff=date.fromisoformat(node["input_cutoff"]),
            evidence=evidence,
            profiles=profiles,
            fallback_profile_id="balanced",
            mode=mode,
            showcase_directive=directive,
        )
        return packet, factor_round_evidence_id

    def _deliberate_portfolio(
        self,
        *,
        node: dict[str, Any],
        factor_packet: DecisionPacket,
        factor_round: dict[str, Any],
        web_evidence: dict[str, Any],
        round_id: str,
        instruction: str,
        deterministic_director: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        packet, factor_round_evidence_id = self._portfolio_packet(
            node=node,
            factor_packet=factor_packet,
            factor_round=factor_round,
            web_evidence=web_evidence,
        )
        directive = packet.showcase_directive
        if (
            deterministic_director
            and packet.mode == CouncilMode.SHOWCASE_REENACTMENT
            and directive is not None
        ):
            # The showcase director already chose the profile and industries from
            # the realised segment.  Apply that decision deterministically instead
            # of asking an LLM to re-derive it (which silently degraded to a
            # neutral policy whenever the call failed).
            profile = approved_profiles()[directive.target_profile_id]
            portfolio_round = {
                "round_id": round_id,
                "factor_round_id": factor_round["round_id"],
                "origin": "showcase_director",
                "created_at": _now(),
                "selected_profile_id": profile.profile_id,
                "stock_target": profile.stock_target,
                "target_beta": profile.target_beta,
                "beta_tolerance": profile.beta_tolerance,
                "industry_overweights": list(directive.target_industry_overweights),
                "industry_underweights": list(directive.target_industry_underweights),
                "industry_active_tilt": directive.target_industry_active_tilt,
                "rationale": directive.retrospective_outcome_summary,
                "evidence_ids": list(packet.evidence_ids),
                "dissent": [],
                "confidence": 1.0,
                "fallback_used": False,
                "fallback_reason": None,
                "valid": True,
                "validation_errors": [],
                "model": "deterministic-showcase-director",
                "prompt_hash": PORTFOLIO_PROMPT_VERSION,
                "token_usage": None,
                "packet_digest": packet.packet_digest,
                "web_evidence_digest": web_evidence.get("evidence_digest"),
                "raw_text": None,
            }
            return portfolio_round, packet.model_dump(mode="json")
        common_prompt = (
            PORTFOLIO_SHOWCASE_PROMPT
            if packet.mode == CouncilMode.SHOWCASE_REENACTMENT
            else PORTFOLIO_RESEARCH_PROMPT
        )
        system = (
            f"{common_prompt}\n\nYou are the chair for the second-stage Portfolio Agenda. "
            "The Factor Agenda has already finished. Use its selected groups as an upstream input, "
            "but never revise them. Choose exactly one approved profile and only approved industry "
            "tilt levels. If industry_snapshot_uses_future_information is true in research mode, "
            "industry_overweights and industry_underweights must be empty and "
            "industry_active_tilt must be 0.0. Return JSON only and keep the rationale under 180 words."
        )
        compact_factor = {
            "round_id": factor_round["round_id"],
            "selected_groups": factor_round["selected_groups"],
            "disabled_groups": factor_round["disabled_groups"],
            "rationale": factor_round["rationale"],
            "confidence": factor_round["confidence"],
            "evidence_ids": factor_round["evidence_ids"],
            "agenda_evidence_id": factor_round_evidence_id,
        }
        prompt = (
            f"Schema:\n{json.dumps(PortfolioChairRecommendation.model_json_schema(), ensure_ascii=False)}\n\n"
            f"Human instruction shared by both agendas:\n{instruction}\n\n"
            f"Accepted Factor Agenda input:\n{json.dumps(compact_factor, ensure_ascii=False)}\n\n"
            f"Portfolio packet:\n{packet.model_dump_json(indent=2)}"
        )
        result = self.client_factory().complete_json(
            call_id=f"portfolio-chair-{round_id}",
            system_prompt=system,
            user_prompt=prompt,
        )
        validation_errors: list[str]
        try:
            payload = dict(result.payload)
            if payload.get("type") == "json_object":
                payload.pop("type")
            recommendation = PortfolioChairRecommendation.model_validate(payload)
            validation_errors = validate_portfolio_recommendation(packet, recommendation)
            if (
                packet.mode == CouncilMode.RESEARCH
                and packet.evidence.industry_snapshot_uses_future_information
                and (
                    recommendation.industry_overweights
                    or recommendation.industry_underweights
                    or recommendation.industry_active_tilt > 0.0
                )
            ):
                validation_errors.append(
                    "research Portfolio Agenda cannot time industries with a future-dated static snapshot"
                )
        except Exception as error:
            recommendation = None
            validation_errors = [f"{type(error).__name__}: {error}"]
        record = result.record
        selected_profile_id = recommendation.selected_profile_id if recommendation else "balanced"
        profile = default_profiles()[selected_profile_id]
        portfolio_round = {
            "round_id": round_id,
            "factor_round_id": factor_round["round_id"],
            "origin": factor_round["origin"],
            "created_at": _now(),
            "selected_profile_id": selected_profile_id,
            "stock_target": profile.stock_target,
            "target_beta": profile.target_beta,
            "beta_tolerance": profile.beta_tolerance,
            "industry_overweights": recommendation.industry_overweights if recommendation else [],
            "industry_underweights": recommendation.industry_underweights if recommendation else [],
            "industry_active_tilt": recommendation.industry_active_tilt if recommendation else 0.0,
            "rationale": recommendation.rationale if recommendation else "Invalid AI response.",
            "evidence_ids": recommendation.evidence_ids if recommendation else [],
            "dissent": recommendation.dissent if recommendation else [],
            "confidence": recommendation.confidence if recommendation else 0.0,
            "fallback_used": recommendation.use_fallback if recommendation else True,
            "fallback_reason": recommendation.fallback_reason if recommendation else "Invalid AI response.",
            "valid": not validation_errors,
            "validation_errors": validation_errors,
            "model": record.model,
            "prompt_hash": record.prompt_hash,
            "prompt_version": PORTFOLIO_PROMPT_VERSION,
            "token_usage": {"input": record.input_tokens, "output": record.output_tokens},
            "packet_digest": packet.packet_digest,
            "web_evidence_digest": web_evidence.get("evidence_digest"),
            "raw_text": record.raw_text,
        }
        return portfolio_round, packet.model_dump(mode="json")

    def _path(self, session_id: str) -> Path:
        if not session_id or any(char not in "0123456789abcdef" for char in session_id):
            raise KeyError("unknown replay session")
        return self.session_root / session_id / "session.json"

    def _load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError("unknown replay session")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, session: dict[str, Any]) -> None:
        session["updated_at"] = _now()
        session["version"] = _digest({key: value for key, value in session.items() if key != "version"})[:16]
        path = self._path(session["session_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, session)

    @staticmethod
    def _round_from_decision(decision: CouncilDecision) -> dict[str, Any]:
        return {
            "round_id": "round-0",
            "previous_round_id": None,
            "origin": "saved_council_decision",
            "created_at": decision.created_at.isoformat(),
            "human_instruction": None,
            "selected_groups": decision.selected_groups,
            "disabled_groups": decision.disabled_groups,
            "rationale": decision.rationale,
            "evidence_ids": decision.evidence_ids,
            "dissent": decision.dissent,
            "confidence": decision.confidence,
            "valid": not decision.validation_errors,
            "validation_errors": decision.validation_errors,
            "model": "saved-artifact",
            "prompt_hash": decision.prompt_version,
            "token_usage": None,
            "raw_text": None,
        }

    @staticmethod
    def _quarter_ends(start: date, end: date) -> list[date]:
        result = []
        year, month = start.year, ((start.month - 1) // 3 + 1) * 3
        while True:
            next_month = month + 1
            next_year = year
            if next_month == 13:
                next_month, next_year = 1, year + 1
            quarter_end = date(next_year, next_month, 1) - timedelta(days=1)
            if quarter_end > end:
                break
            if quarter_end >= start:
                result.append(quarter_end)
            month += 3
            if month > 12:
                month -= 12
                year += 1
        return result

    @staticmethod
    def _rebase_packet(
        packet: DecisionPacket,
        *,
        decision_at: date,
        segment_start: date,
        segment_end: date,
    ) -> DecisionPacket:
        payload = packet.model_dump(mode="json")
        payload["decision_at"] = decision_at.isoformat()
        # The packet keeps its own input cutoff: rebasing it to the decision date
        # would misrepresent stale diagnostics as current-quarter evidence.
        if payload.get("showcase_directive") is not None:
            payload["showcase_directive"]["future_window_start"] = segment_start.isoformat()
            payload["showcase_directive"]["future_window_end"] = segment_end.isoformat()
        payload.pop("packet_digest", None)
        payload["packet_digest"] = _digest(payload)
        return DecisionPacket.model_validate(payload)

    @staticmethod
    def _packet_for_node(node: dict[str, Any]) -> DecisionPacket:
        if node.get("packet_payload") is not None:
            return DecisionPacket.model_validate(node["packet_payload"])
        return _load_packet(Path(node["packet_path"]))

    @staticmethod
    def _discover_nodes() -> list[dict[str, Any]]:
        by_date: dict[str, tuple[int, float, Path, Path]] = {}
        for priority, root in enumerate(COUNCIL_ROOTS):
            if not root.exists():
                continue
            for decision_path in root.rglob("decision.json"):
                packet_path = decision_path.with_name("packet.json")
                if not packet_path.exists():
                    continue
                try:
                    decision = CouncilDecision.model_validate_json(decision_path.read_bytes())
                    _load_packet(packet_path)
                except Exception:
                    continue
                key = decision.decision_at.isoformat()
                rank = (len(COUNCIL_ROOTS) - priority, decision_path.stat().st_mtime)
                current = by_date.get(key)
                if current is None or rank > (current[0], current[1]):
                    by_date[key] = (rank[0], rank[1], decision_path, packet_path)
        templates = []
        for decision_date, (_, _, decision_path, packet_path) in sorted(by_date.items()):
            templates.append((
                date.fromisoformat(decision_date),
                CouncilDecision.model_validate_json(decision_path.read_bytes()),
                _load_packet(packet_path),
                decision_path,
                packet_path,
            ))
        if not templates:
            return []
        replay_end = date.fromisoformat(DEFAULT_REPLAY_END)
        quarter_ends = ReplayService._quarter_ends(templates[0][0], replay_end)
        nodes: list[dict[str, Any]] = []
        for index, quarter_end in enumerate(quarter_ends):
            eligible_templates = [item for item in templates if item[0] <= quarter_end]
            _, source_decision, source_packet, decision_path, packet_path = eligible_templates[-1]
            segment_start_date = quarter_end + timedelta(days=1)
            segment_end_date = (
                quarter_ends[index + 1] if index + 1 < len(quarter_ends) else replay_end
            )
            packet = ReplayService._rebase_packet(
                source_packet,
                decision_at=quarter_end,
                segment_start=segment_start_date,
                segment_end=segment_end_date,
            )
            decision = source_decision.model_copy(update={
                "run_id": f"quarterly-{quarter_end.isoformat()}-{packet.packet_digest[:10]}",
                "created_at": datetime.now().astimezone(),
                "decision_at": quarter_end,
                "input_cutoff": quarter_end,
                "packet_digest": packet.packet_digest,
                "rationale": (
                    "Quarterly automatic proposal carried forward from the latest eligible "
                    f"Council evidence dated {source_packet.input_cutoff.isoformat()}. "
                    + source_decision.rationale
                ),
            })
            decision_date = quarter_end.isoformat()
            round_item = ReplayService._round_from_decision(decision)
            round_item["origin"] = "quarterly_automatic_proposal"
            round_item["model"] = "quarterly-carry-forward"
            evidence_age_days = max(0, (quarter_end - source_packet.input_cutoff).days)
            evidence_status = "current" if evidence_age_days == 0 else "carry_forward"
            nodes.append({
                "node_id": f"factor-council-{decision_date}",
                "decision_at": decision_date,
                "input_cutoff": decision.input_cutoff.isoformat(),
                "evidence_as_of": source_packet.input_cutoff.isoformat(),
                "evidence_status": evidence_status,
                "evidence_age_days": evidence_age_days,
                "evidence_stale": evidence_status != "current" and evidence_age_days > 92,
                "frequency": "quarterly",
                "segment_start": segment_start_date.isoformat(),
                "segment_end": segment_end_date.isoformat(),
                "mode": decision.mode.value,
                "uses_hindsight": decision.uses_hindsight,
                "disclosure": decision.disclosure,
                "packet_digest": decision.packet_digest,
                "packet_path": str(packet_path),
                "decision_path": str(decision_path),
                "packet_payload": packet.model_dump(mode="json"),
                "candidate_groups": [item.group_id for item in packet.factor_groups],
                "constraints": packet.constraints.model_dump(mode="json"),
                "status": "draft",
                "accepted_round_id": None,
                "rounds": [round_item],
                "portfolio_rounds": [ReplayService._initial_portfolio_round()],
                "run": {"state": "idle", "error": None, "curve": [], "metrics": {}},
            })
        return nodes

    def create_session(self, automatic: bool = False, start_node: str | None = None) -> dict[str, Any]:
        with self._lock:
            nodes = self._discover_nodes()
            if not nodes:
                raise RuntimeError("no reusable Factor Council artifacts were found")
            start_index = 0
            if start_node:
                match = next(
                    (index for index, item in enumerate(nodes)
                     if item.get("node_id") == start_node or item.get("decision_at") == start_node),
                    None,
                )
                if match is None:
                    raise ValueError(f"unknown start node: {start_node}")
                start_index = match
                for earlier in nodes[:match]:
                    if earlier.get("accepted_round_id") is None:
                        candidate = next(
                            (item for item in reversed(earlier.get("rounds", [])) if item.get("valid")),
                            None,
                        )
                        if candidate:
                            earlier["accepted_round_id"] = candidate["round_id"]
                            earlier["status"] = "accepted"
            session_id = uuid.uuid4().hex
            session = {
                "schema": "aster-interactive-replay-v1",
                "session_id": session_id,
                "created_at": _now(),
                "updated_at": _now(),
                "version": "",
                "max_reconsideration_rounds": 3,
                "decision_frequency": "quarterly",
                "automation_mode": "automatic" if automatic else "interactive",
                "automation_state": "deciding" if automatic else "manual",
                "current_node_index": start_index,
                "playback": {"state": "paused", "node_id": None},
                "nodes": nodes,
            }
            if not automatic and self.launch_runs:
                session["nodes"][start_index]["status"] = "deciding"
            self._save(session)
        if automatic:
            if self.launch_runs:
                thread = threading.Thread(
                    target=self._run_automatic_session,
                    args=(session_id,),
                    daemon=True,
                )
                thread.start()
            return self.get_session(session_id)
        if self.launch_runs:
            prepared_node = nodes[start_index] if start_node is not None else nodes[0]
            thread = threading.Thread(
                target=self._prepare_interactive_node,
                args=(session_id, prepared_node["node_id"]),
                daemon=True,
            )
            thread.start()
        return _public_session(session)

    def _prepare_interactive_node(self, session_id: str, node_id: str) -> None:
        instruction = (
            "Perform the scheduled quarterly review. First reassess the factor groups using only "
            "eligible evidence, then run the bounded Portfolio Agenda on that validated factor "
            "package to select an approved beta profile and industry policy."
        )
        error_text = None
        try:
            self.rethink(session_id, node_id, instruction)
        except Exception as error:
            error_text = f"{type(error).__name__}: {error}"
        with self._lock:
            session = self._load(session_id)
            node = self._node(session, node_id)
            if error_text is None and node["rounds"][-1]["origin"] == "human_reconsideration":
                node["rounds"][-1]["origin"] = "quarterly_automatic_proposal"
                node["portfolio_rounds"][-1]["origin"] = "quarterly_automatic_proposal"
                write_json_atomic(
                    self._path(session_id).parent
                    / f"{node_id}_{node['rounds'][-1]['round_id']}.json",
                    node["rounds"][-1],
                )
                write_json_atomic(
                    self._path(session_id).parent
                    / f"{node_id}_{node['portfolio_rounds'][-1]['round_id']}_portfolio.json",
                    node["portfolio_rounds"][-1],
                )
            if node["accepted_round_id"] is None:
                node["status"] = "draft" if error_text is None else "failed"
            if error_text:
                node["automation_error"] = error_text
            self._save(session)

    def _run_automatic_session(self, session_id: str) -> None:
        session = self._load(session_id)
        for index, listed_node in enumerate(session["nodes"]):
            node_id = listed_node["node_id"]
            instruction = (
                "Perform the scheduled quarterly factor review automatically. Reassess the prior "
                "selection using only this packet, keep a required baseline group, control redundancy "
                "and turnover, and classify every candidate. If evidence is carried forward, explicitly "
                "treat that staleness as a limitation rather than inventing new facts."
            )
            error_text = None
            try:
                self.rethink(session_id, node_id, instruction)
            except Exception as error:
                error_text = f"{type(error).__name__}: {error}"
            with self._lock:
                session = self._load(session_id)
                node = self._node(session, node_id)
                portfolio_by_round = {
                    item["round_id"]: item for item in node.get("portfolio_rounds", [])
                }
                valid_rounds = [
                    item for item in node["rounds"]
                    if item["valid"]
                    and portfolio_by_round.get(item["round_id"], {}).get("valid", False)
                ]
                if not valid_rounds:
                    node["status"] = "failed"
                    node["automation_error"] = error_text or "no valid quarterly recommendation"
                    session["automation_state"] = "failed"
                    self._save(session)
                    return
                selected_round = valid_rounds[-1]
                if selected_round["origin"] == "human_reconsideration":
                    selected_round["origin"] = "quarterly_automatic_proposal"
                    portfolio_by_round[selected_round["round_id"]]["origin"] = (
                        "quarterly_automatic_proposal"
                    )
                    round_path = (
                        self._path(session_id).parent
                        / f"{node_id}_{selected_round['round_id']}.json"
                    )
                    write_json_atomic(round_path, selected_round)
                    write_json_atomic(
                        self._path(session_id).parent
                        / f"{node_id}_{selected_round['round_id']}_portfolio.json",
                        portfolio_by_round[selected_round["round_id"]],
                    )
                node["accepted_round_id"] = selected_round["round_id"]
                node["accepted_at"] = _now()
                node["status"] = "accepted"
                if error_text:
                    node["automation_error"] = error_text
                session["current_node_index"] = index
                self._save(session)
        with self._lock:
            session = self._load(session_id)
            session["automation_state"] = "backtesting"
            self._save(session)
            final_node_id = session["nodes"][-1]["node_id"]
        self.run_node(session_id, final_node_id)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return _public_session(self._load(session_id))

    @staticmethod
    def _node(session: dict[str, Any], node_id: str) -> dict[str, Any]:
        for node in session["nodes"]:
            if node["node_id"] == node_id:
                return node
        raise KeyError("unknown replay node")

    def rethink(self, session_id: str, node_id: str, instruction: str) -> dict[str, Any]:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("human instruction cannot be empty")
        if len(instruction) > 2000:
            raise ValueError("human instruction exceeds 2000 characters")
        with self._lock:
            session = self._load(session_id)
            node = self._node(session, node_id)
            if node["accepted_round_id"] is not None:
                raise ValueError("accepted Council node is immutable")
            reconsiderations = sum(item["origin"] == "human_reconsideration" for item in node["rounds"])
            if reconsiderations >= session["max_reconsideration_rounds"]:
                raise ValueError("maximum reconsideration rounds reached")
            packet = self._packet_for_node(node)
            previous = node["rounds"][-1]
            round_id = f"round-{len(node['rounds'])}"
            automatic_session = session.get("automation_mode") == "automatic"
            existing_web_evidence = node.get("web_evidence")
            web_request = {
                "node_id": node_id,
                "decision_at": date.fromisoformat(node["decision_at"]),
                "input_cutoff": date.fromisoformat(node["input_cutoff"]),
                "mode": node["mode"],
                "candidate_groups": node["candidate_groups"],
            }
        web_evidence = existing_web_evidence
        if web_evidence is None and self.web_search_enabled:
            try:
                web_evidence = self.web_collector_factory().collect(**web_request)
            except Exception as error:
                web_evidence = {
                    "schema": "aster-web-evidence-v1",
                    **{key: value.isoformat() if isinstance(value, date) else value for key, value in web_request.items() if key != "candidate_groups"},
                    "provider": "deepseek-search-api",
                    "captured_at": _now(),
                    "queries": [],
                    "accepted": [],
                    "rejected": [],
                    "errors": [f"{type(error).__name__}: {error}"],
                    "disclosure": None,
                }
                web_evidence["evidence_digest"] = _digest(web_evidence)
            with self._lock:
                session = self._load(session_id)
                node = self._node(session, node_id)
                node["web_evidence"] = web_evidence
                self._save(session)
                write_json_atomic(
                    self._path(session_id).parent / f"{node_id}_web_evidence.json",
                    web_evidence,
                )
        if web_evidence:
            cutoff_iso = node["decision_at"]
            accepted = []
            rejected = list(web_evidence.get("rejected", []))
            for item in web_evidence.get("accepted", []):
                published = str(item.get("published_at") or "")[:10]
                if published and published <= cutoff_iso:
                    accepted.append(item)
                else:
                    rejected.append({**item, "reason": "published after decision date"})
            web_evidence = {**web_evidence, "accepted": accepted, "rejected": rejected}

        if web_evidence is None:
            web_evidence = {
                "evidence_digest": None,
                "accepted": [],
                "rejected": [],
                "errors": ["web search disabled"],
            }
        compact_web_evidence = {
            "evidence_digest": web_evidence.get("evidence_digest"),
            "disclosure": web_evidence.get("disclosure"),
            "errors": web_evidence.get("errors", []),
            "sources": web_evidence.get("accepted", []),
        }
        web_evidence_ids = {
            item["evidence_id"] for item in web_evidence.get("accepted", [])
        }
        schema = ChairRecommendation.model_json_schema()
        system = (
            "You are the chair of an audited factor-selection council. Reconsider the prior "
            "recommendation in light of the human research instruction. The instruction is advice, "
            "not permission to add unknown factors, bypass constraints, cite unknown evidence, or "
            "hide hindsight. Return JSON only. Keep rationale under 160 words, dissent to at most "
            "three short items, and cite only decisive evidence IDs."
        )
        prompt = (
            f"Schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Human instruction:\n{instruction}\n\n"
            f"Prior round:\n{json.dumps(previous, ensure_ascii=False)}\n\n"
            "Audited web evidence (cite its evidence_id when used):\n"
            f"{json.dumps(compact_web_evidence, ensure_ascii=False)}\n\n"
            f"Decision packet:\n{json.dumps(_interactive_packet(packet), ensure_ascii=False)}"
        )
        result = self.client_factory().complete_json(
            call_id=f"interactive-chair-{len(node['rounds'])}",
            system_prompt=system,
            user_prompt=prompt,
        )
        validation_errors: list[str]
        try:
            recommendation_payload = dict(result.payload)
            # DeepSeek occasionally echoes the OpenAI response-format marker as
            # a top-level payload field.  It is transport metadata, not a
            # Council decision field; only this exact known wrapper is removed.
            if recommendation_payload.get("type") == "json_object":
                recommendation_payload.pop("type")
            recommendation = ChairRecommendation.model_validate(recommendation_payload)
            validation_errors = validate_recommendation(
                packet,
                recommendation,
                extra_evidence_ids=web_evidence_ids,
            )
            # Interactive showcase rounds may deviate from the director's original target, but all
            # ordinary group/evidence constraints and the hindsight disclosure remain enforced.
            validation_errors = [
                item for item in validation_errors
                if item != "showcase chair must select the Demo Director target groups"
            ]
        except Exception as error:
            recommendation = None
            validation_errors = [f"{type(error).__name__}: {error}"]
        record = result.record
        factor_round = {
            "round_id": round_id,
            "previous_round_id": previous["round_id"],
            "origin": "human_reconsideration",
            "created_at": _now(),
            "human_instruction": instruction,
            "selected_groups": recommendation.selected_groups if recommendation else [],
            "disabled_groups": recommendation.disabled_groups if recommendation else [],
            "rationale": recommendation.rationale if recommendation else "Invalid AI response.",
            "evidence_ids": recommendation.evidence_ids if recommendation else [],
            "dissent": recommendation.dissent if recommendation else [],
            "confidence": recommendation.confidence if recommendation else 0.0,
            "valid": not validation_errors,
            "validation_errors": validation_errors,
            "model": record.model,
            "prompt_hash": record.prompt_hash,
            "prompt_version": FACTOR_PROMPT_VERSION,
            "token_usage": {
                "input": record.input_tokens,
                "output": record.output_tokens,
            },
            "web_evidence_digest": web_evidence.get("evidence_digest"),
            "web_evidence_ids": sorted(web_evidence_ids),
            "raw_text": record.raw_text,
        }
        if factor_round["valid"]:
            try:
                portfolio_round, portfolio_packet_payload = self._deliberate_portfolio(
                    node=node,
                    factor_packet=packet,
                    factor_round=factor_round,
                    web_evidence=web_evidence,
                    round_id=round_id,
                    instruction=instruction,
                    deterministic_director=automatic_session,
                )
            except Exception as error:
                portfolio_round = self._initial_portfolio_round(round_id)
                portfolio_round.update({
                    "factor_round_id": round_id,
                    "origin": "human_reconsideration",
                    "valid": False,
                    "validation_errors": [f"{type(error).__name__}: {error}"],
                    "rationale": "Portfolio Agenda could not complete.",
                })
                portfolio_packet_payload = None
        else:
            portfolio_round = self._initial_portfolio_round(round_id)
            portfolio_round.update({
                "factor_round_id": round_id,
                "origin": "human_reconsideration",
                "valid": False,
                "validation_errors": ["Portfolio Agenda was skipped because Factor Agenda is invalid."],
                "rationale": "Portfolio Agenda requires a valid upstream Factor Agenda.",
            })
            portfolio_packet_payload = None
        with self._lock:
            session = self._load(session_id)
            node = self._node(session, node_id)
            if f"round-{len(node['rounds'])}" != round_id:
                raise RuntimeError("Council node changed while deliberation was in progress")
            node["rounds"].append(factor_round)
            node["portfolio_rounds"].append(portfolio_round)
            if portfolio_packet_payload is not None:
                node["portfolio_packet_payload"] = portfolio_packet_payload
            self._save(session)
            round_path = self._path(session_id).parent / f"{node_id}_{round_id}.json"
            write_json_atomic(round_path, factor_round)
            write_json_atomic(
                self._path(session_id).parent / f"{node_id}_{round_id}_portfolio.json",
                portfolio_round,
            )
            if portfolio_packet_payload is not None:
                write_json_atomic(
                    self._path(session_id).parent / f"{node_id}_{round_id}_portfolio_packet.json",
                    portfolio_packet_payload,
                )
            return _public_session(session)

    def accept(self, session_id: str, node_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._load(session_id)
            node = self._node(session, node_id)
            if node["accepted_round_id"] is not None:
                return _public_session(session)
            round_item = node["rounds"][-1]
            portfolio_round = node["portfolio_rounds"][-1]
            if portfolio_round["round_id"] != round_item["round_id"]:
                raise ValueError("Factor and Portfolio Agenda rounds are not aligned")
            if not round_item["valid"] or not portfolio_round["valid"]:
                raise ValueError("invalid Council decision package cannot be accepted")
            if self.launch_runs and portfolio_round["model"] == "deterministic-policy":
                raise ValueError("wait for the two AI agendas before accepting the package")
            node["accepted_round_id"] = round_item["round_id"]
            node["accepted_at"] = _now()
            node["status"] = "accepted"
            self._save(session)
            return _public_session(session)

    def _write_schedules(
        self, session: dict[str, Any], through_node: dict[str, Any]
    ) -> tuple[Path, Path]:
        factor_entries = []
        portfolio_entries = []
        for node in session["nodes"]:
            if node["accepted_round_id"] is None:
                break
            selected_round = next(
                item for item in node["rounds"] if item["round_id"] == node["accepted_round_id"]
            )
            selected_portfolio_round = next(
                item for item in node["portfolio_rounds"]
                if item["round_id"] == node["accepted_round_id"]
            )
            factor_entries.append({
                "node_id": node["node_id"],
                "round_id": selected_round["round_id"],
                "effective_from": node["segment_start"],
                "effective_to": node["segment_end"],
                "input_cutoff": node["input_cutoff"],
                "selected_groups": selected_round["selected_groups"],
                "packet_digest": node["packet_digest"],
                "mode": node["mode"],
                "uses_hindsight": node["uses_hindsight"],
                "disclosure": node["disclosure"],
                "web_evidence_digest": selected_round.get("web_evidence_digest"),
                "web_evidence_ids": selected_round.get("web_evidence_ids", []),
            })
            portfolio_entries.append({
                "node_id": node["node_id"],
                "round_id": selected_portfolio_round["round_id"],
                "factor_round_id": selected_portfolio_round["factor_round_id"],
                "effective_from": node["segment_start"],
                "effective_to": node["segment_end"],
                "input_cutoff": node["input_cutoff"],
                "selected_profile_id": selected_portfolio_round["selected_profile_id"],
                "industry_overweights": selected_portfolio_round["industry_overweights"],
                "industry_underweights": selected_portfolio_round["industry_underweights"],
                "industry_active_tilt": selected_portfolio_round["industry_active_tilt"],
                "packet_digest": selected_portfolio_round.get("packet_digest"),
                "mode": node["mode"],
                "uses_hindsight": node["uses_hindsight"],
                "disclosure": node["disclosure"],
                "web_evidence_digest": selected_portfolio_round.get("web_evidence_digest"),
            })
            if node["node_id"] == through_node["node_id"]:
                break
        factor_payload = {
            "schema": "aster-factor-schedule-v1",
            "session_id": session["session_id"],
            "created_at": _now(),
            "entries": factor_entries,
        }
        portfolio_payload = {
            "schema": "aster-portfolio-schedule-v1",
            "session_id": session["session_id"],
            "created_at": _now(),
            "entries": portfolio_entries,
        }
        root = self._path(session["session_id"]).parent
        factor_path = root / f"schedule_{through_node['node_id']}.json"
        portfolio_path = root / f"portfolio_schedule_{through_node['node_id']}.json"
        write_json_atomic(factor_path, factor_payload)
        write_json_atomic(portfolio_path, portfolio_payload)
        return factor_path, portfolio_path

    def run_node(self, session_id: str, node_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._load(session_id)
            node = self._node(session, node_id)
            index = session["nodes"].index(node)
            if node["accepted_round_id"] is None:
                raise ValueError("accept the Council recommendation before running the segment")
            if any(item["accepted_round_id"] is None for item in session["nodes"][:index]):
                raise ValueError("earlier Council nodes must be accepted first")
            if node["run"]["state"] in {"computing", "ready"}:
                return _public_session(session)
            factor_schedule_path, portfolio_schedule_path = self._write_schedules(session, node)
            node["run"] = {"state": "computing", "error": None, "curve": [], "metrics": {}}
            node["status"] = "computing"
            self._save(session)
        if self.launch_runs:
            thread = threading.Thread(
                target=self._execute_run,
                args=(session_id, node_id, factor_schedule_path, portfolio_schedule_path),
                daemon=True,
            )
            thread.start()
        return self.get_session(session_id)

    def _execute_run(
        self,
        session_id: str,
        node_id: str,
        factor_schedule_path: Path,
        portfolio_schedule_path: Path,
    ) -> None:
        with self._lock:
            session = self._load(session_id)
            node = self._node(session, node_id)
            output_root = self._path(session_id).parent / "runs" / node_id
            segment_end = node["segment_end"]
            curve_start = (
                session["nodes"][0]["segment_start"]
                if session.get("automation_mode") == "automatic"
                else node["segment_start"]
            )
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(PROJECT_ROOT / "scripts" / "run_real_pipeline.ps1"),
            "-StartDate", "2019-01-01", "-EndDate", segment_end,
            "-OutputRoot", str(output_root),
            "-FactorSchedule", str(factor_schedule_path),
            "-PortfolioSchedule", str(portfolio_schedule_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout)[-4000:])
            rows = []
            peak = 0.0
            with (output_root / "daily.csv").open(encoding="utf-8", newline="") as handle:
                for item in csv.DictReader(handle):
                    if item["date"] < curve_start:
                        continue
                    nav = float(item["nav"])
                    peak = max(peak, nav)
                    rows.append({
                        "date": item["date"],
                        "nav": nav,
                        "drawdown": nav / peak - 1.0 if peak else 0.0,
                        "beta": float(item["estimated_net_beta"]),
                        "profile": item["profile_id"],
                    })
            metrics = json.loads((output_root / "metrics.json").read_text(encoding="utf-8"))
            next_node_id = None
            with self._lock:
                session = self._load(session_id)
                node = self._node(session, node_id)
                node["run"] = {
                    "state": "ready", "error": None, "curve": rows, "metrics": metrics,
                    "output_root": str(output_root), "completed_at": _now(),
                }
                node["status"] = "ready"
                if session.get("automation_mode") == "automatic":
                    session["automation_state"] = "ready"
                else:
                    index = session["nodes"].index(node)
                    if index + 1 < len(session["nodes"]):
                        next_node = session["nodes"][index + 1]
                        if len(next_node["rounds"]) == 1:
                            next_node["status"] = "deciding"
                            next_node_id = next_node["node_id"]
                        session["current_node_index"] = index + 1
                self._save(session)
            if next_node_id is not None:
                self._prepare_interactive_node(session_id, next_node_id)
        except Exception as error:
            with self._lock:
                session = self._load(session_id)
                node = self._node(session, node_id)
                node["run"]["state"] = "failed"
                node["run"]["error"] = f"{type(error).__name__}: {error}"
                node["status"] = "failed"
                if session.get("automation_mode") == "automatic":
                    session["automation_state"] = "failed"
                self._save(session)

    def set_playback(self, session_id: str, node_id: str, state: str) -> dict[str, Any]:
        if state not in {"playing", "paused"}:
            raise ValueError("invalid playback state")
        with self._lock:
            session = self._load(session_id)
            node = self._node(session, node_id)
            if node["run"]["state"] != "ready":
                raise ValueError("segment must finish computing before playback")
            session["playback"] = {"state": state, "node_id": node_id, "changed_at": _now()}
            self._save(session)
            return _public_session(session)

