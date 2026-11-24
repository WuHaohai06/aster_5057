import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from aster_council.evidence import DecisionPacketBuilder
from aster_council.llm import StaticCouncilClient
from aster_council.orchestrator import CouncilOrchestrator
from aster_council.schemas import (
    ChairRecommendation,
    CouncilMode,
    FactorShowcaseDirective,
    SHOWCASE_DISCLOSURE,
)
from aster_council.validation import validate_recommendation


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "council"


def build_packet():
    return DecisionPacketBuilder().build_from_files(
        registry_path=CONFIG / "smoke_factor_registry.json",
        diagnostics_path=CONFIG / "smoke_diagnostics.json",
        market_path=CONFIG / "smoke_market_state.json",
        policy_path=CONFIG / "smoke_policy.json",
        decision_at=date(2024, 12, 31),
        input_cutoff=date(2024, 12, 31),
    )


class CouncilTest(unittest.TestCase):
    def test_showcase_packet_and_decision_are_permanently_disclosed(self) -> None:
        directive = FactorShowcaseDirective(
            target_selected_groups=[
                "conventional_low_vol",
                "shock_reversal",
                "volume_confirmed_momentum",
            ],
            future_window_start=date(2025, 1, 1),
            future_window_end=date(2025, 3, 31),
            retrospective_outcome_summary=(
                "Hindsight selected the clearest factor combination for the course demo."
            ),
        )
        packet = DecisionPacketBuilder().build_from_files(
            registry_path=CONFIG / "smoke_factor_registry.json",
            diagnostics_path=CONFIG / "smoke_diagnostics.json",
            market_path=CONFIG / "smoke_market_state.json",
            policy_path=CONFIG / "smoke_policy.json",
            decision_at=date(2024, 12, 31),
            input_cutoff=date(2024, 12, 31),
            mode=CouncilMode.SHOWCASE_REENACTMENT,
            showcase_directive=directive,
        )
        responses = json.loads(
            (CONFIG / "smoke_static_responses.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            result = CouncilOrchestrator(StaticCouncilClient(responses)).run(
                packet, Path(directory)
            )
        self.assertEqual(result.decision.mode, CouncilMode.SHOWCASE_REENACTMENT)
        self.assertTrue(result.decision.uses_hindsight)
        self.assertEqual(result.decision.disclosure, SHOWCASE_DISCLOSURE)
        self.assertEqual(
            set(result.decision.selected_groups), set(directive.target_selected_groups)
        )

    def test_packet_is_deterministic_and_excludes_unmatured_labels(self) -> None:
        first = build_packet()
        second = build_packet()
        self.assertEqual(first.packet_digest, second.packet_digest)
        self.assertIn("unmatured_demo_factor", first.excluded_factors)
        factor_ids = {
            factor.factor_id for group in first.factor_groups for factor in group.factors
        }
        self.assertNotIn("unmatured_demo_factor", factor_ids)
        shock = next(
            factor
            for group in first.factor_groups
            for factor in group.factors
            if factor.factor_id == "pv_a01_shock_reversal"
        )
        self.assertIn("subsequently reverse", shock.economic_hypothesis)
        self.assertTrue(shock.mechanism_explanation)
        self.assertTrue(shock.falsification_criteria)
        self.assertIn("TS_ZSCORE", shock.formula)

    def test_static_council_accepts_valid_chair_mask_and_writes_audit(self) -> None:
        responses = json.loads(
            (CONFIG / "smoke_static_responses.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            result = CouncilOrchestrator(StaticCouncilClient(responses)).run(
                build_packet(), Path(directory)
            )
            self.assertEqual(result.decision.status, "accepted")
            self.assertFalse(result.decision.fallback_used)
            self.assertTrue((result.run_dir / "packet.json").exists())
            self.assertTrue((result.run_dir / "decision.json").exists())
            self.assertTrue((result.run_dir / "manifest.json").exists())
            self.assertEqual(len(list((result.run_dir / "ballots").glob("*.json"))), 3)
            self.assertEqual(len(list((result.run_dir / "calls").glob("*.json"))), 4)
            for ballot_path in (result.run_dir / "ballots").glob("*.json"):
                ballot = json.loads(ballot_path.read_text(encoding="utf-8"))
                self.assertEqual(len(ballot["mechanism_reviews"]), 4)

    def test_missing_mechanism_review_forces_fallback(self) -> None:
        responses = json.loads(
            (CONFIG / "smoke_static_responses.json").read_text(encoding="utf-8")
        )
        responses["factor_evidence_reviewer"]["mechanism_reviews"].pop()
        with tempfile.TemporaryDirectory() as directory:
            result = CouncilOrchestrator(StaticCouncilClient(responses)).run(
                build_packet(), Path(directory)
            )
        self.assertEqual(result.decision.status, "fallback")
        self.assertIn("factor_evidence_reviewer", result.decision.reviewer_failures)

    def test_invalid_chair_mask_uses_fixed_fallback(self) -> None:
        responses = json.loads(
            (CONFIG / "smoke_static_responses.json").read_text(encoding="utf-8")
        )
        responses["chair"]["selected_groups"] = ["shock_reversal"]
        responses["chair"]["disabled_groups"] = [
            "conventional_low_vol",
            "conventional_reversal",
            "volume_confirmed_momentum",
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = CouncilOrchestrator(StaticCouncilClient(responses)).run(
                build_packet(), Path(directory)
            )
            self.assertEqual(result.decision.status, "fallback")
            self.assertTrue(result.decision.fallback_used)
            self.assertEqual(
                result.decision.selected_groups,
                ["conventional_reversal", "conventional_low_vol"],
            )
            self.assertTrue(result.decision.validation_errors)

    def test_explicit_fallback_group_order_has_no_semantic_effect(self) -> None:
        packet = build_packet()
        recommendation = ChairRecommendation(
            decision_at=packet.decision_at,
            selected_groups=["conventional_low_vol", "conventional_reversal"],
            disabled_groups=["shock_reversal", "volume_confirmed_momentum"],
            rationale="Evidence is explicitly synthetic, so use the declared fixed fallback pool.",
            evidence_ids=["market:synthetic-smoke:2024-12-31"],
            confidence=0.8,
            use_fallback=True,
            fallback_reason="Synthetic smoke evidence is not investment research evidence.",
        )
        self.assertEqual(validate_recommendation(packet, recommendation), [])

    def test_future_market_evidence_is_rejected(self) -> None:
        builder = DecisionPacketBuilder()
        with self.assertRaisesRegex(ValueError, "market evidence is after input_cutoff"):
            builder.build_from_files(
                registry_path=CONFIG / "smoke_factor_registry.json",
                diagnostics_path=CONFIG / "smoke_diagnostics.json",
                market_path=CONFIG / "smoke_market_state.json",
                policy_path=CONFIG / "smoke_policy.json",
                decision_at=date(2024, 12, 31),
                input_cutoff=date(2024, 12, 30),
            )


if __name__ == "__main__":
    unittest.main()
