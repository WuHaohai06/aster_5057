"""AI Council that selects one pre-approved deterministic portfolio profile."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from aster_council.llm import StructuredLLM, StructuredLLMError
from aster_council.schemas import (
    CouncilMode,
    LLMCallRecord,
    SHOWCASE_DISCLOSURE,
)
from aster_council.storage import write_run_artifacts

from .schemas import PortfolioProfile, StrictModel


PORTFOLIO_RESEARCH_PROMPT_VERSION = "aster-portfolio-council-research-v1.2"
PORTFOLIO_SHOWCASE_PROMPT_VERSION = "aster-portfolio-council-showcase-v1.0"


class PortfolioReviewerRole(str, Enum):
    ALPHA = "alpha_allocation_reviewer"
    RISK = "portfolio_risk_reviewer"
    EXECUTION = "execution_liquidity_reviewer"


class PortfolioOperatingEvidence(StrictModel):
    as_of_close: date
    benchmark_return_20: float
    benchmark_return_60: float
    benchmark_volatility_20: float = Field(ge=0.0)
    breadth_above_60d_average: float = Field(ge=0.0, le=1.0)
    forecast_cross_section_std: float = Field(ge=0.0)
    trailing_rank_ic: float | None = None
    current_drawdown: float = Field(le=0.0)
    realized_portfolio_volatility_20: float = Field(ge=0.0)
    current_estimated_net_beta: float
    tradable_coverage: float = Field(ge=0.0, le=1.0)
    recent_one_way_turnover: float = Field(ge=0.0)
    source_ids: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class PortfolioShowcaseDirective(StrictModel):
    uses_hindsight_for_scenario_selection: Literal[True] = True
    narrative_style: Literal["ex_ante_reenactment"] = "ex_ante_reenactment"
    target_profile_id: str
    future_window_start: date
    future_window_end: date
    retrospective_outcome_summary: str = Field(min_length=20)
    disclosure: str = SHOWCASE_DISCLOSURE

    @model_validator(mode="after")
    def validate_directive(self) -> "PortfolioShowcaseDirective":
        if self.disclosure != SHOWCASE_DISCLOSURE:
            raise ValueError("showcase directive must retain the fixed disclosure")
        if self.future_window_end < self.future_window_start:
            raise ValueError("future_window_end cannot precede future_window_start")
        return self


class PortfolioCouncilPacket(StrictModel):
    packet_version: Literal["aster-portfolio-council-packet-v1"] = (
        "aster-portfolio-council-packet-v1"
    )
    decision_at: date
    input_cutoff: date
    evidence: PortfolioOperatingEvidence
    profiles: list[PortfolioProfile] = Field(min_length=1)
    fallback_profile_id: str
    evidence_ids: list[str] = Field(min_length=1)
    mode: CouncilMode = CouncilMode.RESEARCH
    showcase_directive: PortfolioShowcaseDirective | None = None
    packet_digest: str

    @model_validator(mode="after")
    def validate_packet(self) -> "PortfolioCouncilPacket":
        if self.input_cutoff > self.decision_at:
            raise ValueError("input_cutoff cannot be after decision_at")
        if self.evidence.as_of_close > self.input_cutoff:
            raise ValueError("operating evidence is after input_cutoff")
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("profile IDs must be unique")
        if self.fallback_profile_id not in profile_ids:
            raise ValueError("fallback profile must be an approved candidate")
        if self.mode == CouncilMode.RESEARCH and self.showcase_directive is not None:
            raise ValueError("research mode cannot contain a showcase_directive")
        if self.mode == CouncilMode.SHOWCASE_REENACTMENT:
            if self.showcase_directive is None:
                raise ValueError("showcase_reenactment requires a showcase_directive")
            if self.showcase_directive.future_window_start <= self.decision_at:
                raise ValueError("showcase future window must start after decision_at")
            if self.showcase_directive.target_profile_id not in profile_ids:
                raise ValueError("showcase target profile is not approved")
        return self


class PortfolioProfileVote(StrictModel):
    profile_id: str
    action: Literal["recommend", "oppose", "abstain"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=10)
    evidence_ids: list[str] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)


class PortfolioReviewerBallot(StrictModel):
    role: PortfolioReviewerRole
    decision_at: date
    votes: list[PortfolioProfileVote] = Field(min_length=1)
    summary: str = Field(min_length=10)


class PortfolioChairRecommendation(StrictModel):
    decision_at: date
    selected_profile_id: str
    rationale: str = Field(min_length=20)
    evidence_ids: list[str] = Field(min_length=1)
    dissent: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    use_fallback: bool = False
    fallback_reason: str | None = None

    @model_validator(mode="after")
    def validate_fallback(self) -> "PortfolioChairRecommendation":
        if self.use_fallback and not self.fallback_reason:
            raise ValueError("fallback_reason is required when use_fallback is true")
        return self


class PortfolioCouncilDecision(StrictModel):
    run_id: str
    created_at: datetime
    decision_at: date
    input_cutoff: date
    packet_digest: str
    prompt_version: str
    mode: CouncilMode = CouncilMode.RESEARCH
    uses_hindsight: bool = False
    disclosure: str | None = None
    showcase_future_window_start: date | None = None
    showcase_future_window_end: date | None = None
    status: Literal["accepted", "fallback"]
    selected_profile_id: str
    rationale: str
    evidence_ids: list[str]
    dissent: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    fallback_used: bool
    fallback_reason: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    reviewer_failures: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode_disclosure(self) -> "PortfolioCouncilDecision":
        if self.mode == CouncilMode.RESEARCH:
            if self.uses_hindsight or self.disclosure is not None:
                raise ValueError("research decisions cannot be marked as hindsight")
        elif not self.uses_hindsight or self.disclosure != SHOWCASE_DISCLOSURE:
            raise ValueError("showcase decisions require the fixed hindsight disclosure")
        if self.mode == CouncilMode.RESEARCH:
            if self.showcase_future_window_start or self.showcase_future_window_end:
                raise ValueError("research decisions cannot carry a showcase future window")
        elif not self.showcase_future_window_start or not self.showcase_future_window_end:
            raise ValueError("showcase decisions require an explicit future window")
        return self


def build_portfolio_council_packet(
    *,
    decision_at: date,
    input_cutoff: date,
    evidence: PortfolioOperatingEvidence,
    profiles: list[PortfolioProfile],
    fallback_profile_id: str,
    mode: CouncilMode = CouncilMode.RESEARCH,
    showcase_directive: PortfolioShowcaseDirective | None = None,
) -> PortfolioCouncilPacket:
    payload = {
        "packet_version": "aster-portfolio-council-packet-v1",
        "decision_at": decision_at.isoformat(),
        "input_cutoff": input_cutoff.isoformat(),
        "evidence": evidence.model_dump(mode="json"),
        "profiles": [profile.model_dump(mode="json") for profile in profiles],
        "fallback_profile_id": fallback_profile_id,
        "evidence_ids": sorted(set(evidence.source_ids)),
        "mode": mode.value,
        "showcase_directive": (
            showcase_directive.model_dump(mode="json") if showcase_directive else None
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["packet_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return PortfolioCouncilPacket.model_validate(payload)


RESEARCH_PROMPT = """
You are part of a bounded portfolio-policy council. Choose only among the
approved profiles in the packet. Never invent numeric exposure, alter profile
parameters, place trades, change factor formulas, or use information after the
input cutoff. Cite only supplied evidence IDs. Return one JSON object matching
the schema and no Markdown. Do not emit response-format metadata such as a
top-level `type` key. If evidence is synthetic, incomplete or internally
inconsistent, prefer the declared fallback profile. For reviewer ballots, the
votes array MUST contain exactly one explicit vote for every approved profile
listed in the packet. Never omit a profile, even when it is clearly unsuitable.
""".strip()

SHOWCASE_PROMPT = """
You are reenacting a historical portfolio-policy meeting for a clearly labelled
course demo. A Demo Director used hindsight to choose target_profile_id in the
showcase_directive. Discuss the decision in the natural present tense of
decision_at and make that approved target persuasive using only supplied PIT
evidence IDs. Do not cite the retrospective outcome as if it were known then,
fabricate news, invent exposures, or alter profile parameters. Vote exactly once
on every approved profile and return only one JSON object matching the schema.
""".strip()


def _prompt_version(mode: CouncilMode) -> str:
    if mode == CouncilMode.SHOWCASE_REENACTMENT:
        return PORTFOLIO_SHOWCASE_PROMPT_VERSION
    return PORTFOLIO_RESEARCH_PROMPT_VERSION


def _common_prompt(mode: CouncilMode) -> str:
    return SHOWCASE_PROMPT if mode == CouncilMode.SHOWCASE_REENACTMENT else RESEARCH_PROMPT

ROLE_PROMPTS = {
    PortfolioReviewerRole.ALPHA: "Assess forecast breadth, dispersion and matured predictive evidence without overriding risk limits.",
    PortfolioReviewerRole.RISK: "Prioritize drawdown, volatility, beta stability and preservation of the hard portfolio limits.",
    PortfolioReviewerRole.EXECUTION: "Prioritize tradable coverage, turnover, costs, margin headroom and implementability.",
}


def _validate_ballot(
    packet: PortfolioCouncilPacket,
    ballot: PortfolioReviewerBallot,
    role: PortfolioReviewerRole,
) -> list[str]:
    errors = []
    profiles = {profile.profile_id for profile in packet.profiles}
    if ballot.role != role:
        errors.append("reviewer role mismatch")
    if ballot.decision_at != packet.decision_at:
        errors.append("ballot decision date mismatch")
    voted = [vote.profile_id for vote in ballot.votes]
    if len(voted) != len(set(voted)) or set(voted) != profiles:
        errors.append("ballot must vote exactly once on every approved profile")
    for vote in ballot.votes:
        if not set(vote.evidence_ids).issubset(packet.evidence_ids):
            errors.append(f"{vote.profile_id} cites unknown evidence")
    return errors


def _validate_chair(
    packet: PortfolioCouncilPacket, recommendation: PortfolioChairRecommendation
) -> list[str]:
    errors = []
    profiles = {profile.profile_id for profile in packet.profiles}
    if recommendation.decision_at != packet.decision_at:
        errors.append("chair decision date mismatch")
    if recommendation.selected_profile_id not in profiles:
        errors.append("chair selected an unapproved profile")
    if not set(recommendation.evidence_ids).issubset(packet.evidence_ids):
        errors.append("chair cites unknown evidence")
    if recommendation.use_fallback and recommendation.selected_profile_id != packet.fallback_profile_id:
        errors.append("explicit fallback must select fallback_profile_id")
    if packet.mode == CouncilMode.SHOWCASE_REENACTMENT:
        assert packet.showcase_directive is not None
        if recommendation.selected_profile_id != packet.showcase_directive.target_profile_id:
            errors.append("showcase chair must select the Demo Director target profile")
        if recommendation.use_fallback:
            errors.append("showcase target selection is not the research fallback")
    return errors


class PortfolioCouncilOrchestrator:
    def __init__(self, client: StructuredLLM) -> None:
        self.client = client

    def _review(self, packet: PortfolioCouncilPacket, role: PortfolioReviewerRole):
        prompt = (
            f"Your assigned role ID is exactly {json.dumps(role.value)}. "
            "Set the top-level role field to this exact string; do not use any other role.\n\n"
            f"Schema:\n{json.dumps(PortfolioReviewerBallot.model_json_schema(), ensure_ascii=False)}"
            "\n\nRequired profile IDs (vote exactly once on every one):\n"
            f"{json.dumps([profile.profile_id for profile in packet.profiles], ensure_ascii=False)}"
            f"\n\nPacket:\n{packet.model_dump_json(indent=2)}"
        )
        result = self.client.complete_json(
            call_id=role.value,
            system_prompt=(
                f"{_common_prompt(packet.mode)}\n\nYour assigned role ID is exactly {role.value}. "
                f"Return that exact value in the role field.\n{ROLE_PROMPTS[role]}"
            ),
            user_prompt=prompt,
        )
        try:
            ballot = PortfolioReviewerBallot.model_validate(result.payload)
            errors = _validate_ballot(packet, ballot, role)
            if errors:
                raise ValueError("; ".join(errors))
        except Exception as error:
            wrapped = ValueError(str(error))
            wrapped.record = result.record  # type: ignore[attr-defined]
            raise wrapped from error
        return ballot, result.record

    @staticmethod
    def _fallback(
        packet: PortfolioCouncilPacket,
        now: datetime,
        run_id: str,
        reason: str,
        failures: dict[str, str],
        errors: list[str],
    ) -> PortfolioCouncilDecision:
        if packet.mode == CouncilMode.SHOWCASE_REENACTMENT:
            assert packet.showcase_directive is not None
            selected_profile_id = packet.showcase_directive.target_profile_id
        else:
            selected_profile_id = packet.fallback_profile_id
        return PortfolioCouncilDecision(
            run_id=run_id,
            created_at=now,
            decision_at=packet.decision_at,
            input_cutoff=packet.input_cutoff,
            packet_digest=packet.packet_digest,
            prompt_version=_prompt_version(packet.mode),
            mode=packet.mode,
            uses_hindsight=packet.mode == CouncilMode.SHOWCASE_REENACTMENT,
            disclosure=(SHOWCASE_DISCLOSURE if packet.mode == CouncilMode.SHOWCASE_REENACTMENT else None),
            showcase_future_window_start=(
                packet.showcase_directive.future_window_start
                if packet.showcase_directive else None
            ),
            showcase_future_window_end=(
                packet.showcase_directive.future_window_end
                if packet.showcase_directive else None
            ),
            status="fallback",
            selected_profile_id=selected_profile_id,
            rationale="Deterministic portfolio-policy fallback; no LLM-created exposure was used.",
            evidence_ids=packet.evidence_ids,
            confidence=0.0,
            fallback_used=True,
            fallback_reason=reason,
            reviewer_failures=failures,
            validation_errors=errors,
        )

    def run(self, packet: PortfolioCouncilPacket, output_root: Path):
        now = datetime.now().astimezone()
        stamp = now.strftime("%Y%m%dT%H%M%S_%f%z").replace("+", "p").replace("-", "m")
        run_id = f"portfolio_{packet.decision_at}_{stamp}_{packet.packet_digest[:10]}"
        ballots: dict[str, PortfolioReviewerBallot] = {}
        calls: dict[str, LLMCallRecord] = {}
        failures: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._review, packet, role): role for role in PortfolioReviewerRole
            }
            for future in as_completed(futures):
                role = futures[future]
                try:
                    ballot, record = future.result()
                    ballots[role.value] = ballot
                    calls[role.value] = record
                except Exception as error:
                    record = getattr(error, "record", None)
                    if record is not None:
                        calls[role.value] = record
                    failures[role.value] = f"{type(error).__name__}: {error}"
        if failures:
            decision = self._fallback(packet, now, run_id, "reviewer validation failed", failures, [])
            run_dir = write_run_artifacts(
                output_root=output_root,
                packet=packet,  # type: ignore[arg-type]
                ballots=ballots,  # type: ignore[arg-type]
                calls=calls,
                decision=decision,  # type: ignore[arg-type]
            )
            return decision, run_dir

        if packet.mode == CouncilMode.SHOWCASE_REENACTMENT:
            chair_mandate = (
                "Select exactly the Demo Director target_profile_id and preserve material dissent."
            )
        else:
            chair_mandate = (
                "Preserve material dissent and explicitly choose fallback when evidence is weak."
            )
        chair_prompt = (
            f"{_common_prompt(packet.mode)}\nYou are the chair. Select exactly one approved "
            f"profile. {chair_mandate}"
        )
        user_prompt = (
            f"Schema:\n{json.dumps(PortfolioChairRecommendation.model_json_schema(), ensure_ascii=False)}"
            "\n\nThe top-level keys must be exactly: decision_at, selected_profile_id, "
            "rationale, evidence_ids, dissent, confidence, use_fallback, fallback_reason. "
            "Never add a type or json_object key."
            f"\n\nPacket:\n{packet.model_dump_json(indent=2)}"
            f"\n\nBallots:\n{json.dumps({key: value.model_dump(mode='json') for key, value in ballots.items()}, ensure_ascii=False, indent=2)}"
        )
        errors: list[str] = []
        try:
            result = self.client.complete_json(
                call_id="portfolio_chair", system_prompt=chair_prompt, user_prompt=user_prompt
            )
            calls["portfolio_chair"] = result.record
            recommendation = PortfolioChairRecommendation.model_validate(result.payload)
            errors = _validate_chair(packet, recommendation)
            if errors:
                raise ValueError("; ".join(errors))
        except Exception as error:
            if isinstance(error, StructuredLLMError):
                calls["portfolio_chair"] = error.record
            decision = self._fallback(
                packet, now, run_id, f"chair validation failed: {type(error).__name__}", failures, errors or [str(error)]
            )
        else:
            decision = PortfolioCouncilDecision(
                run_id=run_id,
                created_at=now,
                decision_at=packet.decision_at,
                input_cutoff=packet.input_cutoff,
                packet_digest=packet.packet_digest,
                prompt_version=_prompt_version(packet.mode),
                mode=packet.mode,
                uses_hindsight=packet.mode == CouncilMode.SHOWCASE_REENACTMENT,
                disclosure=(SHOWCASE_DISCLOSURE if packet.mode == CouncilMode.SHOWCASE_REENACTMENT else None),
                showcase_future_window_start=(
                    packet.showcase_directive.future_window_start
                    if packet.showcase_directive else None
                ),
                showcase_future_window_end=(
                    packet.showcase_directive.future_window_end
                    if packet.showcase_directive else None
                ),
                status="fallback" if recommendation.use_fallback else "accepted",
                selected_profile_id=recommendation.selected_profile_id,
                rationale=recommendation.rationale,
                evidence_ids=recommendation.evidence_ids,
                dissent=recommendation.dissent,
                confidence=recommendation.confidence,
                fallback_used=recommendation.use_fallback,
                fallback_reason=recommendation.fallback_reason,
            )
        run_dir = write_run_artifacts(
            output_root=output_root,
            packet=packet,  # type: ignore[arg-type]
            ballots=ballots,  # type: ignore[arg-type]
            calls=calls,
            decision=decision,  # type: ignore[arg-type]
        )
        return decision, run_dir
