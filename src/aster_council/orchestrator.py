"""Bounded parallel-review workflow with deterministic validation/fallback."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .llm import StructuredLLM, StructuredLLMError
from .prompts import chair_system, prompt_version, reviewer_system
from .schemas import (
    ChairRecommendation,
    CouncilDecision,
    CouncilMode,
    DecisionPacket,
    LLMCallRecord,
    ReviewerBallot,
    ReviewerRole,
    SHOWCASE_DISCLOSURE,
)
from .storage import write_run_artifacts
from .validation import validate_ballot, validate_recommendation


@dataclass(frozen=True)
class CouncilRunResult:
    decision: CouncilDecision
    run_dir: Path


class ReviewerValidationError(ValueError):
    def __init__(self, message: str, record: LLMCallRecord) -> None:
        super().__init__(message)
        self.record = record


class CouncilOrchestrator:
    def __init__(self, client: StructuredLLM) -> None:
        self.client = client

    @staticmethod
    def _run_id(packet: DecisionPacket, now: datetime) -> str:
        stamp = now.strftime("%Y%m%dT%H%M%S_%f%z").replace("+", "p").replace("-", "m")
        return f"{packet.decision_at}_{stamp}_{packet.packet_digest[:10]}"

    @staticmethod
    def _reviewer_prompt(packet: DecisionPacket, role: ReviewerRole) -> str:
        schema = ReviewerBallot.model_json_schema()
        return (
            f"Prompt version: {prompt_version(packet.mode)}\n"
            f"Council mode: {packet.mode.value}\n"
            f"Assigned role: {role.value}\n"
            "Return JSON matching this schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}\n\n"
            "Point-in-time decision packet:\n"
            f"{packet.model_dump_json(indent=2)}"
        )

    @staticmethod
    def _chair_prompt(packet: DecisionPacket, ballots: dict[str, ReviewerBallot]) -> str:
        schema = ChairRecommendation.model_json_schema()
        ballot_payload = {
            role: ballot.model_dump(mode="json") for role, ballot in sorted(ballots.items())
        }
        return (
            f"Prompt version: {prompt_version(packet.mode)}\n"
            f"Council mode: {packet.mode.value}\n"
            "Return JSON matching this schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}\n\n"
            "Point-in-time decision packet:\n"
            f"{packet.model_dump_json(indent=2)}\n\n"
            "Independent reviewer ballots:\n"
            f"{json.dumps(ballot_payload, ensure_ascii=False, indent=2)}"
        )

    def _review(self, packet: DecisionPacket, role: ReviewerRole):
        result = self.client.complete_json(
            call_id=role.value,
            system_prompt=reviewer_system(role, packet.mode),
            user_prompt=self._reviewer_prompt(packet, role),
        )
        try:
            ballot = ReviewerBallot.model_validate(result.payload)
            errors = validate_ballot(packet, ballot, role)
            if errors:
                raise ValueError("; ".join(errors))
        except Exception as error:
            raise ReviewerValidationError(str(error), result.record) from error
        return role, ballot, result.record

    @staticmethod
    def _fallback_decision(
        *,
        packet: DecisionPacket,
        now: datetime,
        run_id: str,
        reason: str,
        validation_errors: list[str],
        reviewer_failures: dict[str, str],
    ) -> CouncilDecision:
        if packet.mode == CouncilMode.SHOWCASE_REENACTMENT:
            assert packet.showcase_directive is not None
            selected = list(packet.showcase_directive.target_selected_groups)
        else:
            selected = list(packet.constraints.fallback_groups)
        candidates = [group.group_id for group in packet.factor_groups]
        selected_evidence = [
            factor.evidence_id
            for group in packet.factor_groups
            if group.group_id in selected
            for factor in group.factors
        ]
        return CouncilDecision(
            run_id=run_id,
            created_at=now,
            decision_at=packet.decision_at,
            input_cutoff=packet.input_cutoff,
            packet_digest=packet.packet_digest,
            prompt_version=prompt_version(packet.mode),
            mode=packet.mode,
            uses_hindsight=packet.mode == CouncilMode.SHOWCASE_REENACTMENT,
            disclosure=(SHOWCASE_DISCLOSURE if packet.mode == CouncilMode.SHOWCASE_REENACTMENT else None),
            status="fallback",
            selected_groups=selected,
            disabled_groups=[group for group in candidates if group not in selected],
            rationale="Deterministic fixed-pool fallback; no LLM discretion was applied.",
            evidence_ids=sorted(set(packet.market.source_ids + selected_evidence)),
            dissent=[],
            confidence=0.0,
            fallback_used=True,
            fallback_reason=reason,
            validation_errors=validation_errors,
            reviewer_failures=reviewer_failures,
        )

    def run(self, packet: DecisionPacket, output_root: Path) -> CouncilRunResult:
        now = datetime.now().astimezone()
        run_id = self._run_id(packet, now)
        ballots: dict[str, ReviewerBallot] = {}
        calls: dict[str, LLMCallRecord] = {}
        failures: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=len(ReviewerRole)) as executor:
            futures = {
                executor.submit(self._review, packet, role): role for role in ReviewerRole
            }
            for future in as_completed(futures):
                role = futures[future]
                try:
                    _, ballot, record = future.result()
                    ballots[role.value] = ballot
                    calls[role.value] = record
                except Exception as error:
                    record = getattr(error, "record", None)
                    if record is not None:
                        calls[role.value] = record
                    failures[role.value] = f"{type(error).__name__}: {error}"

        if failures:
            decision = self._fallback_decision(
                packet=packet,
                now=now,
                run_id=run_id,
                reason="one or more reviewer calls failed validation",
                validation_errors=[],
                reviewer_failures=failures,
            )
            run_dir = write_run_artifacts(
                output_root=output_root,
                packet=packet,
                ballots=ballots,
                calls=calls,
                decision=decision,
            )
            return CouncilRunResult(decision, run_dir)

        chair_result = None
        validation_errors: list[str] = []
        try:
            chair_result = self.client.complete_json(
                call_id="chair",
                system_prompt=chair_system(packet.mode),
                user_prompt=self._chair_prompt(packet, ballots),
            )
            calls["chair"] = chair_result.record
            recommendation = ChairRecommendation.model_validate(chair_result.payload)
            validation_errors = validate_recommendation(packet, recommendation)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
        except Exception as error:
            if isinstance(error, StructuredLLMError):
                calls["chair"] = error.record
            decision = self._fallback_decision(
                packet=packet,
                now=now,
                run_id=run_id,
                reason=f"chair call failed validation: {type(error).__name__}",
                validation_errors=validation_errors or [str(error)],
                reviewer_failures=failures,
            )
        else:
            used_fallback = recommendation.use_fallback
            decision = CouncilDecision(
                run_id=run_id,
                created_at=now,
                decision_at=packet.decision_at,
                input_cutoff=packet.input_cutoff,
                packet_digest=packet.packet_digest,
                prompt_version=prompt_version(packet.mode),
                mode=packet.mode,
                uses_hindsight=packet.mode == CouncilMode.SHOWCASE_REENACTMENT,
                disclosure=(SHOWCASE_DISCLOSURE if packet.mode == CouncilMode.SHOWCASE_REENACTMENT else None),
                status="fallback" if used_fallback else "accepted",
                selected_groups=recommendation.selected_groups,
                disabled_groups=recommendation.disabled_groups,
                rationale=recommendation.rationale,
                evidence_ids=recommendation.evidence_ids,
                dissent=recommendation.dissent,
                confidence=recommendation.confidence,
                fallback_used=used_fallback,
                fallback_reason=recommendation.fallback_reason,
                reviewer_failures=failures,
            )

        run_dir = write_run_artifacts(
            output_root=output_root,
            packet=packet,
            ballots=ballots,
            calls=calls,
            decision=decision,
        )
        return CouncilRunResult(decision, run_dir)
