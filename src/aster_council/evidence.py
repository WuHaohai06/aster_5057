"""Build point-in-time Council packets from deterministic evidence files."""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field

from .schemas import (
    CouncilMode,
    CouncilConstraints,
    DecisionPacket,
    FactorShowcaseDirective,
    FactorEvidence,
    FactorGroupEvidence,
    MarketEvidence,
    StrictModel,
)


class RegistryEntry(StrictModel):
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
    approval_status: Literal["approved", "rejected", "candidate"]


class FactorRegistry(StrictModel):
    version: str
    universe: str
    factors: list[RegistryEntry] = Field(min_length=1)


class FactorDiagnostic(StrictModel):
    factor_id: str
    observed_at: date
    latest_label_date: date
    observations: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    rank_ic_mean: float
    rank_ic_ir: float
    rank_ic_positive_fraction: float = Field(ge=0.0, le=1.0)
    turnover: float = Field(ge=0.0)
    max_abs_correlation: float = Field(ge=0.0, le=1.0)
    yearly_rank_ic: dict[str, float] = Field(default_factory=dict)
    decay_rank_ic: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DiagnosticBundle(StrictModel):
    label_horizon_days: int = Field(ge=1)
    factors: list[FactorDiagnostic] = Field(min_length=1)


class MarketState(MarketEvidence):
    pass


class CouncilPolicy(StrictModel):
    constraints: CouncilConstraints


def _load(path: Path, model_type):
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _packet_digest(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_text(canonical)


class DecisionPacketBuilder:
    def build_from_files(
        self,
        *,
        registry_path: Path,
        diagnostics_path: Path,
        market_path: Path,
        policy_path: Path,
        decision_at: date,
        input_cutoff: date,
        mode: CouncilMode = CouncilMode.RESEARCH,
        showcase_directive: FactorShowcaseDirective | None = None,
    ) -> DecisionPacket:
        return self.build(
            registry=_load(registry_path, FactorRegistry),
            diagnostics=_load(diagnostics_path, DiagnosticBundle),
            market=_load(market_path, MarketState),
            policy=_load(policy_path, CouncilPolicy),
            decision_at=decision_at,
            input_cutoff=input_cutoff,
            mode=mode,
            showcase_directive=showcase_directive,
        )

    def build(
        self,
        *,
        registry: FactorRegistry,
        diagnostics: DiagnosticBundle,
        market: MarketState,
        policy: CouncilPolicy,
        decision_at: date,
        input_cutoff: date,
        mode: CouncilMode = CouncilMode.RESEARCH,
        showcase_directive: FactorShowcaseDirective | None = None,
    ) -> DecisionPacket:
        if input_cutoff > decision_at:
            raise ValueError("input_cutoff cannot be after decision_at")
        if market.as_of_close > input_cutoff:
            raise ValueError("market evidence is after input_cutoff")

        diagnostic_map = {item.factor_id: item for item in diagnostics.factors}
        if len(diagnostic_map) != len(diagnostics.factors):
            raise ValueError("factor diagnostics contain duplicate factor IDs")

        grouped: dict[str, list[FactorEvidence]] = {}
        excluded: dict[str, str] = {}
        constraints = policy.constraints
        for entry in registry.factors:
            if entry.approval_status != "approved":
                excluded[entry.factor_id] = f"registry status is {entry.approval_status}"
                continue
            diagnostic = diagnostic_map.get(entry.factor_id)
            if diagnostic is None:
                excluded[entry.factor_id] = "missing deterministic diagnostics"
                continue
            if diagnostic.observed_at > input_cutoff:
                excluded[entry.factor_id] = "diagnostics observed after input cutoff"
                continue
            if diagnostic.latest_label_date > input_cutoff:
                excluded[entry.factor_id] = "forward label has not matured by input cutoff"
                continue
            if diagnostic.coverage < constraints.min_factor_coverage:
                excluded[entry.factor_id] = "coverage below hard minimum"
                continue
            if diagnostic.observations < constraints.min_ic_observations:
                excluded[entry.factor_id] = "IC observations below hard minimum"
                continue

            evidence_id = f"factor:{entry.factor_id}:diagnostics:{diagnostic.observed_at}"
            evidence = FactorEvidence(
                factor_id=entry.factor_id,
                factor_group=entry.factor_group,
                description=entry.description,
                economic_hypothesis=entry.economic_hypothesis,
                mechanism_explanation=entry.mechanism_explanation,
                expected_direction=entry.expected_direction,
                falsification_criteria=entry.falsification_criteria,
                mechanism_source=entry.mechanism_source,
                origin=entry.origin,
                formula=entry.formula,
                formula_hash=_hash_text(entry.formula),
                coverage=diagnostic.coverage,
                observations=diagnostic.observations,
                latest_label_date=diagnostic.latest_label_date,
                rank_ic_mean=diagnostic.rank_ic_mean,
                rank_ic_ir=diagnostic.rank_ic_ir,
                rank_ic_positive_fraction=diagnostic.rank_ic_positive_fraction,
                turnover=diagnostic.turnover,
                max_abs_correlation=diagnostic.max_abs_correlation,
                yearly_rank_ic=diagnostic.yearly_rank_ic,
                decay_rank_ic=diagnostic.decay_rank_ic,
                warnings=diagnostic.warnings,
                evidence_id=evidence_id,
            )
            grouped.setdefault(entry.factor_group, []).append(evidence)

        factor_groups: list[FactorGroupEvidence] = []
        for group_id, factors in sorted(grouped.items()):
            warnings = sorted({warning for factor in factors for warning in factor.warnings})
            factor_groups.append(
                FactorGroupEvidence(
                    group_id=group_id,
                    factors=sorted(factors, key=lambda item: item.factor_id),
                    coverage_min=min(item.coverage for item in factors),
                    observations_min=min(item.observations for item in factors),
                    rank_ic_mean_median=statistics.median(item.rank_ic_mean for item in factors),
                    rank_ic_ir_median=statistics.median(item.rank_ic_ir for item in factors),
                    turnover_median=statistics.median(item.turnover for item in factors),
                    max_abs_correlation=max(item.max_abs_correlation for item in factors),
                    warnings=warnings,
                )
            )
        if not factor_groups:
            raise ValueError("no approved factors passed the point-in-time hard gates")

        candidates = {group.group_id for group in factor_groups}
        missing_fallback = set(constraints.fallback_groups).difference(candidates)
        if missing_fallback:
            raise ValueError(f"fallback groups failed evidence gates: {sorted(missing_fallback)}")
        missing_required = set(constraints.required_at_least_one_from).difference(candidates)
        if missing_required:
            raise ValueError(f"required baseline groups are unavailable: {sorted(missing_required)}")

        evidence_ids = sorted(
            set(market.source_ids).union(
                factor.evidence_id for group in factor_groups for factor in group.factors
            )
        )
        payload = {
            "packet_version": "aster-council-packet-v2",
            "decision_at": decision_at.isoformat(),
            "input_cutoff": input_cutoff.isoformat(),
            "universe": registry.universe,
            "factor_registry_version": registry.version,
            "label_horizon_days": diagnostics.label_horizon_days,
            "market": market.model_dump(mode="json"),
            "factor_groups": [group.model_dump(mode="json") for group in factor_groups],
            "excluded_factors": excluded,
            "constraints": constraints.model_dump(mode="json"),
            "evidence_ids": evidence_ids,
            "mode": mode.value,
            "showcase_directive": (
                showcase_directive.model_dump(mode="json") if showcase_directive else None
            ),
        }
        payload["packet_digest"] = _packet_digest(payload)
        return DecisionPacket.model_validate(payload)


def write_packet(packet: DecisionPacket, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
