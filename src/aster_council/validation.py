"""Deterministic validation and fallback for LLM recommendations."""

from __future__ import annotations

from .schemas import (
    ChairRecommendation,
    CouncilMode,
    DecisionPacket,
    ReviewerBallot,
    ReviewerRole,
)


def validate_ballot(
    packet: DecisionPacket, ballot: ReviewerBallot, expected_role: ReviewerRole
) -> list[str]:
    errors: list[str] = []
    candidates = {group.group_id for group in packet.factor_groups}
    if ballot.role != expected_role:
        errors.append(f"role mismatch: expected {expected_role.value}, got {ballot.role.value}")
    if ballot.decision_at != packet.decision_at:
        errors.append("ballot decision_at does not match packet")
    voted = [vote.group_id for vote in ballot.votes]
    if len(voted) != len(set(voted)):
        errors.append("ballot contains duplicate group votes")
    if set(voted) != candidates:
        errors.append("ballot must vote once on every candidate group")
    for vote in ballot.votes:
        unknown = set(vote.evidence_ids).difference(packet.evidence_ids)
        if unknown:
            errors.append(f"{vote.group_id} cites unknown evidence: {sorted(unknown)}")
    return errors


def validate_recommendation(
    packet: DecisionPacket, recommendation: ChairRecommendation
) -> list[str]:
    errors: list[str] = []
    candidates = {group.group_id for group in packet.factor_groups}
    selected = recommendation.selected_groups
    disabled = recommendation.disabled_groups
    if recommendation.decision_at != packet.decision_at:
        errors.append("chair decision_at does not match packet")
    if len(selected) != len(set(selected)) or len(disabled) != len(set(disabled)):
        errors.append("chair group lists contain duplicates")
    if set(selected).intersection(disabled):
        errors.append("selected_groups and disabled_groups overlap")
    if set(selected).union(disabled) != candidates:
        errors.append("chair must classify every candidate group exactly once")
    if not set(selected).issubset(candidates):
        errors.append("chair selected an unknown factor group")
    constraints = packet.constraints
    if not constraints.min_groups <= len(selected) <= constraints.max_groups:
        errors.append("selected group count violates min_groups/max_groups")
    required = set(constraints.required_at_least_one_from)
    if required and not required.intersection(selected):
        errors.append("selection does not retain a required baseline group")
    unknown_evidence = set(recommendation.evidence_ids).difference(packet.evidence_ids)
    if unknown_evidence:
        errors.append(f"chair cites unknown evidence: {sorted(unknown_evidence)}")
    if recommendation.use_fallback and set(selected) != set(constraints.fallback_groups):
        errors.append("explicit fallback must use exactly the declared fallback_groups")
    if packet.mode == CouncilMode.SHOWCASE_REENACTMENT:
        assert packet.showcase_directive is not None
        target = set(packet.showcase_directive.target_selected_groups)
        if set(selected) != target:
            errors.append("showcase chair must select the Demo Director target groups")
        if recommendation.use_fallback:
            errors.append("showcase target selection is not the research fallback")
    return errors
