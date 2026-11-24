"""Strict data contracts for the Aster factor-selection council."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewerRole(str, Enum):
    MARKET = "market_regime_reviewer"
    FACTOR = "factor_evidence_reviewer"
    RISK = "risk_data_reviewer"


class CouncilMode(str, Enum):
    RESEARCH = "research"
    SHOWCASE_REENACTMENT = "showcase_reenactment"


SHOWCASE_DISCLOSURE = (
    "Retrospective course-demo reenactment: hindsight selected the showcased "
    "scenario; the Council narrative is not a live or point-in-time prediction."
)


class FactorShowcaseDirective(StrictModel):
    uses_hindsight_for_scenario_selection: Literal[True] = True
    narrative_style: Literal["ex_ante_reenactment"] = "ex_ante_reenactment"
    target_selected_groups: list[str] = Field(min_length=1)
    future_window_start: date
    future_window_end: date
    retrospective_outcome_summary: str = Field(min_length=20)
    disclosure: str = SHOWCASE_DISCLOSURE

    @model_validator(mode="after")
    def validate_directive(self) -> "FactorShowcaseDirective":
        if self.disclosure != SHOWCASE_DISCLOSURE:
            raise ValueError("showcase directive must retain the fixed disclosure")
        if self.future_window_end < self.future_window_start:
            raise ValueError("future_window_end cannot precede future_window_start")
        if len(self.target_selected_groups) != len(set(self.target_selected_groups)):
            raise ValueError("target_selected_groups must be unique")
        return self


class FactorEvidence(StrictModel):
    factor_id: str
    factor_group: str
    description: str
    economic_hypothesis: str = ""
    mechanism_explanation: str = ""
    expected_direction: str = ""
    falsification_criteria: list[str] = Field(default_factory=list)
    mechanism_source: str = ""
    origin: str
    formula: str
    formula_hash: str
    coverage: float = Field(ge=0.0, le=1.0)
    observations: int = Field(ge=0)
    latest_label_date: date
    rank_ic_mean: float
    rank_ic_ir: float
    rank_ic_positive_fraction: float = Field(ge=0.0, le=1.0)
    turnover: float = Field(ge=0.0)
    max_abs_correlation: float = Field(ge=0.0, le=1.0)
    yearly_rank_ic: dict[str, float] = Field(default_factory=dict)
    decay_rank_ic: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    evidence_id: str


class FactorGroupEvidence(StrictModel):
    group_id: str
    factors: list[FactorEvidence] = Field(min_length=1)
    coverage_min: float = Field(ge=0.0, le=1.0)
    observations_min: int = Field(ge=0)
    rank_ic_mean_median: float
    rank_ic_ir_median: float
    turnover_median: float = Field(ge=0.0)
    max_abs_correlation: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class MarketEvidence(StrictModel):
    as_of_close: date
    benchmark: str = "SH000905"
    benchmark_return_20: float | None = None
    benchmark_return_60: float | None = None
    benchmark_volatility_20: float | None = Field(default=None, ge=0.0)
    breadth_above_60d_average: float | None = Field(default=None, ge=0.0, le=1.0)
    cross_section_dispersion_20: float | None = Field(default=None, ge=0.0)
    average_pairwise_correlation_60: float | None = Field(default=None, ge=-1.0, le=1.0)
    source_ids: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class CouncilConstraints(StrictModel):
    min_groups: int = Field(default=2, ge=1)
    max_groups: int = Field(default=5, ge=1)
    min_factor_coverage: float = Field(default=0.8, ge=0.0, le=1.0)
    min_ic_observations: int = Field(default=24, ge=1)
    required_at_least_one_from: list[str] = Field(default_factory=list)
    fallback_groups: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> "CouncilConstraints":
        if self.min_groups > self.max_groups:
            raise ValueError("min_groups cannot exceed max_groups")
        if not self.min_groups <= len(self.fallback_groups) <= self.max_groups:
            raise ValueError("fallback_groups must satisfy min_groups/max_groups")
        if self.required_at_least_one_from and not set(self.fallback_groups).intersection(
            self.required_at_least_one_from
        ):
            raise ValueError("fallback_groups must retain a required baseline group")
        return self


class DecisionPacket(StrictModel):
    packet_version: Literal["aster-council-packet-v1", "aster-council-packet-v2"] = (
        "aster-council-packet-v2"
    )
    decision_at: date
    input_cutoff: date
    universe: str
    factor_registry_version: str
    label_horizon_days: int = Field(ge=1)
    market: MarketEvidence
    factor_groups: list[FactorGroupEvidence] = Field(min_length=1)
    excluded_factors: dict[str, str] = Field(default_factory=dict)
    constraints: CouncilConstraints
    evidence_ids: list[str] = Field(min_length=1)
    mode: CouncilMode = CouncilMode.RESEARCH
    showcase_directive: FactorShowcaseDirective | None = None
    packet_digest: str

    @model_validator(mode="after")
    def validate_packet(self) -> "DecisionPacket":
        if self.input_cutoff > self.decision_at:
            raise ValueError("input_cutoff cannot be after decision_at")
        if self.market.as_of_close > self.input_cutoff:
            raise ValueError("market evidence is after input_cutoff")
        groups = {group.group_id for group in self.factor_groups}
        if len(groups) != len(self.factor_groups):
            raise ValueError("factor group IDs must be unique")
        if not set(self.constraints.fallback_groups).issubset(groups):
            raise ValueError("fallback_groups must be present in factor_groups")
        if not set(self.constraints.required_at_least_one_from).issubset(groups):
            raise ValueError("required baseline groups must be candidates")
        for group in self.factor_groups:
            for factor in group.factors:
                if factor.latest_label_date > self.input_cutoff:
                    raise ValueError(f"factor {factor.factor_id} uses an unmatured label")
        if self.mode == CouncilMode.RESEARCH and self.showcase_directive is not None:
            raise ValueError("research mode cannot contain a showcase_directive")
        if self.mode == CouncilMode.SHOWCASE_REENACTMENT:
            if self.showcase_directive is None:
                raise ValueError("showcase_reenactment requires a showcase_directive")
            if self.showcase_directive.future_window_start <= self.decision_at:
                raise ValueError("showcase future window must start after decision_at")
            selected = set(self.showcase_directive.target_selected_groups)
            if not selected.issubset(groups):
                raise ValueError("showcase target contains an unknown factor group")
            if not self.constraints.min_groups <= len(selected) <= self.constraints.max_groups:
                raise ValueError("showcase target violates min_groups/max_groups")
            required = set(self.constraints.required_at_least_one_from)
            if required and not required.intersection(selected):
                raise ValueError("showcase target must retain a required baseline group")
        return self


class GroupVote(StrictModel):
    group_id: str
    action: Literal["enable", "disable", "abstain"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=10)
    evidence_ids: list[str] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)


class MechanismReview(StrictModel):
    group_id: str
    assessment: Literal["supported", "plausible", "weak", "unsupported", "not_available"]
    pit_consistent: bool
    falsifiable: bool
    rationale: str = Field(min_length=10)
    evidence_ids: list[str] = Field(min_length=1)


class ReviewerBallot(StrictModel):
    role: ReviewerRole
    decision_at: date
    votes: list[GroupVote] = Field(min_length=1)
    mechanism_reviews: list[MechanismReview] = Field(min_length=1)
    summary: str = Field(min_length=10)
    dissent_conditions: list[str] = Field(default_factory=list)


class ChairRecommendation(StrictModel):
    decision_at: date
    selected_groups: list[str] = Field(min_length=1)
    disabled_groups: list[str]
    rationale: str = Field(min_length=20)
    evidence_ids: list[str] = Field(min_length=1)
    dissent: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    use_fallback: bool = False
    fallback_reason: str | None = None

    @model_validator(mode="after")
    def require_fallback_reason(self) -> "ChairRecommendation":
        if self.use_fallback and not self.fallback_reason:
            raise ValueError("fallback_reason is required when use_fallback is true")
        return self


class LLMCallRecord(StrictModel):
    call_id: str
    model: str
    raw_text: str
    prompt_hash: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class CouncilDecision(StrictModel):
    run_id: str
    created_at: datetime
    decision_at: date
    input_cutoff: date
    packet_digest: str
    prompt_version: str
    mode: CouncilMode = CouncilMode.RESEARCH
    uses_hindsight: bool = False
    disclosure: str | None = None
    status: Literal["accepted", "fallback"]
    selected_groups: list[str] = Field(min_length=1)
    disabled_groups: list[str]
    rationale: str
    evidence_ids: list[str]
    dissent: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    fallback_used: bool
    fallback_reason: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    reviewer_failures: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode_disclosure(self) -> "CouncilDecision":
        if self.mode == CouncilMode.RESEARCH:
            if self.uses_hindsight or self.disclosure is not None:
                raise ValueError("research decisions cannot be marked as hindsight")
        elif not self.uses_hindsight or self.disclosure != SHOWCASE_DISCLOSURE:
            raise ValueError("showcase decisions require the fixed hindsight disclosure")
        return self
