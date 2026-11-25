import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from aster_council.llm import StaticCouncilClient
from aster_council.schemas import CouncilMode, SHOWCASE_DISCLOSURE
from aster_portfolio.council import (
    PortfolioCouncilOrchestrator,
    PortfolioOperatingEvidence,
    PortfolioShowcaseDirective,
    build_portfolio_council_packet,
)
from aster_portfolio.optimizer import PortfolioOptimizationInput, PortfolioOptimizer
from aster_portfolio.schemas import default_profiles


def portfolio_packet(
    mode: CouncilMode = CouncilMode.RESEARCH,
    directive: PortfolioShowcaseDirective | None = None,
):
    evidence = PortfolioOperatingEvidence(
        as_of_close=date(2024, 5, 17),
        benchmark_return_20=0.02,
        benchmark_return_60=0.10,
        benchmark_volatility_20=0.14,
        breadth_above_60d_average=0.75,
        forecast_cross_section_std=0.001,
        trailing_rank_ic=None,
        current_drawdown=-0.05,
        realized_portfolio_volatility_20=0.03,
        current_estimated_net_beta=0.0,
        tradable_coverage=1.0,
        recent_one_way_turnover=0.5,
        source_ids=["synthetic:test:evidence"],
        limitations=["synthetic test evidence"],
    )
    return build_portfolio_council_packet(
        decision_at=date(2024, 5, 17),
        input_cutoff=date(2024, 5, 17),
        evidence=evidence,
        profiles=list(default_profiles().values()),
        fallback_profile_id="balanced",
        mode=mode,
        showcase_directive=directive,
    )


def static_portfolio_responses():
    profiles = ["defensive", "balanced", "opportunistic"]
    responses = {}
    for role in (
        "alpha_allocation_reviewer",
        "portfolio_risk_reviewer",
        "execution_liquidity_reviewer",
    ):
        responses[role] = {
            "role": role,
            "decision_at": "2024-05-17",
            "votes": [
                {
                    "profile_id": profile,
                    "action": "recommend" if profile == "balanced" else "abstain",
                    "confidence": 0.8,
                    "rationale": "Synthetic evidence supports only the declared balanced fallback profile.",
                    "evidence_ids": ["synthetic:test:evidence"],
                    "risks": ["synthetic evidence"],
                }
                for profile in profiles
            ],
            "summary": "Use the declared fallback because evidence is synthetic.",
        }
    responses["portfolio_chair"] = {
        "decision_at": "2024-05-17",
        "selected_profile_id": "balanced",
        "rationale": "The packet is synthetic and does not justify changing the approved default portfolio policy.",
        "evidence_ids": ["synthetic:test:evidence"],
        "dissent": [],
        "confidence": 0.9,
        "use_fallback": True,
        "fallback_reason": "Synthetic evidence is not valid investment evidence.",
    }
    return responses


class PortfolioInfrastructureTest(unittest.TestCase):
    def test_showcase_portfolio_decision_retains_hindsight_disclosure(self) -> None:
        directive = PortfolioShowcaseDirective(
            target_profile_id="balanced",
            future_window_start=date(2024, 5, 20),
            future_window_end=date(2024, 6, 20),
            retrospective_outcome_summary=(
                "Hindsight selected the balanced profile for this course demonstration window."
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            decision, _ = PortfolioCouncilOrchestrator(
                StaticCouncilClient(static_portfolio_responses())
            ).run(
                portfolio_packet(CouncilMode.SHOWCASE_REENACTMENT, directive),
                Path(directory),
            )
        self.assertEqual(decision.mode, CouncilMode.SHOWCASE_REENACTMENT)
        self.assertTrue(decision.uses_hindsight)
        self.assertEqual(decision.disclosure, SHOWCASE_DISCLOSURE)
        self.assertEqual(decision.selected_profile_id, "balanced")

    def test_optimizer_enforces_core_constraints(self) -> None:
        names = [f"SH{600000 + i:06d}" for i in range(30)]
        profile = default_profiles()["balanced"]
        result = PortfolioOptimizer().solve(
            PortfolioOptimizationInput(
                signal_date=date(2024, 5, 17),
                expected_returns=pd.Series(np.linspace(-0.01, 0.02, len(names)), index=names),
                covariance=pd.DataFrame(np.eye(len(names)) * 0.002, index=names, columns=names),
                betas=pd.Series(np.linspace(0.7, 1.2, len(names)), index=names),
                previous_weights=pd.Series(0.0, index=names),
                previous_futures_short=0.0,
                eligible=pd.Series(True, index=names),
                profile=profile,
                turnover_limit=profile.stock_target,
            )
        )
        diagnostics = result.diagnostics
        self.assertAlmostEqual(diagnostics.stock_weight, profile.stock_target, places=5)
        self.assertLessEqual(diagnostics.max_name_weight, profile.name_cap + 1e-6)
        self.assertLessEqual(diagnostics.gross_exposure, profile.max_gross + 1e-6)
        self.assertLessEqual(abs(diagnostics.estimated_net_beta), profile.beta_tolerance + 1e-6)
        self.assertGreaterEqual(diagnostics.cash_weight, profile.cash_buffer - 1e-6)
        self.assertGreaterEqual(diagnostics.cash_weight, diagnostics.margin_required - 1e-6)

    def test_optimizer_enforces_aggressive_industry_rotation(self) -> None:
        names = [f"SH{600000 + i:06d}" for i in range(40)]
        profile = default_profiles()["balanced"]
        industries = pd.Series(
            ["Industry A"] * 20 + ["Industry B"] * 20,
            index=names,
        )
        result = PortfolioOptimizer().solve(
            PortfolioOptimizationInput(
                signal_date=date(2024, 5, 17),
                expected_returns=pd.Series(0.0, index=names),
                covariance=pd.DataFrame(np.eye(len(names)) * 0.002, index=names, columns=names),
                betas=pd.Series(1.0, index=names),
                previous_weights=pd.Series(0.0, index=names),
                previous_futures_short=0.0,
                eligible=pd.Series(True, index=names),
                profile=profile,
                turnover_limit=profile.stock_target,
                industries=industries,
                industry_benchmark_weights=pd.Series(
                    {"Industry A": 0.5, "Industry B": 0.5}
                ),
                industry_overweights=("Industry A",),
                industry_underweights=("Industry B",),
                industry_active_tilt=0.10,
            )
        )
        active = result.diagnostics.industry_active_exposures
        self.assertGreaterEqual(active["Industry A"], 0.10 - 1e-6)
        self.assertLessEqual(active["Industry B"], -0.10 + 1e-6)

    def test_ineligible_legacy_positions_are_sell_only_under_turnover_limit(self) -> None:
        names = [f"SH{600000 + i:06d}" for i in range(30)]
        profile = default_profiles()["balanced"]
        previous = pd.Series(profile.stock_target / len(names), index=names)
        eligible = pd.Series(True, index=names)
        eligible.iloc[:8] = False
        result = PortfolioOptimizer().solve(
            PortfolioOptimizationInput(
                signal_date=date(2024, 6, 14),
                expected_returns=pd.Series(np.linspace(-0.01, 0.02, len(names)), index=names),
                covariance=pd.DataFrame(np.eye(len(names)) * 0.002, index=names, columns=names),
                betas=pd.Series(1.0, index=names),
                previous_weights=previous,
                previous_futures_short=profile.stock_target,
                eligible=eligible,
                profile=profile,
            )
        )
        weights = pd.Series(result.stock_weights)
        self.assertTrue((weights.loc[~eligible] <= previous.loc[~eligible] + 1e-7).all())
        self.assertLessEqual(
            result.diagnostics.one_way_turnover,
            profile.max_one_way_turnover + 1e-6,
        )

    def test_portfolio_council_selects_only_approved_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            decision, run_dir = PortfolioCouncilOrchestrator(
                StaticCouncilClient(static_portfolio_responses())
            ).run(portfolio_packet(), Path(directory))
            self.assertEqual(decision.status, "fallback")
            self.assertEqual(decision.selected_profile_id, "balanced")
            self.assertTrue(decision.fallback_used)
            self.assertEqual(len(list((run_dir / "ballots").glob("*.json"))), 3)
            self.assertEqual(len(list((run_dir / "calls").glob("*.json"))), 4)

    def test_unapproved_chair_profile_triggers_fallback(self) -> None:
        responses = static_portfolio_responses()
        responses["portfolio_chair"]["selected_profile_id"] = "unbounded_leverage"
        responses["portfolio_chair"]["use_fallback"] = False
        responses["portfolio_chair"]["fallback_reason"] = None
        with tempfile.TemporaryDirectory() as directory:
            decision, _ = PortfolioCouncilOrchestrator(StaticCouncilClient(responses)).run(
                portfolio_packet(), Path(directory)
            )
            self.assertEqual(decision.status, "fallback")
            self.assertEqual(decision.selected_profile_id, "balanced")
            self.assertTrue(decision.validation_errors)


if __name__ == "__main__":
    unittest.main()
