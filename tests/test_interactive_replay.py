from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aster_console.replay import ReplayService  # noqa: E402
from aster_portfolio.forecaster import WalkForwardRidgeForecaster  # noqa: E402


class InteractiveReplayTest(unittest.TestCase):
    def test_acceptance_writes_an_audited_factor_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ReplayService(session_root=Path(directory), launch_runs=False)
            session = service.create_session()
            self.assertEqual(session["decision_frequency"], "quarterly")
            self.assertEqual(len(session["nodes"]), 20)
            self.assertEqual(session["nodes"][0]["decision_at"], "2021-12-31")
            self.assertEqual(session["nodes"][0]["segment_end"], "2022-03-31")
            self.assertEqual(session["nodes"][-1]["decision_at"], "2026-09-30")
            node = session["nodes"][0]
            accepted = service.accept(session["session_id"], node["node_id"])
            self.assertEqual(accepted["nodes"][0]["status"], "accepted")
            computing = service.run_node(session["session_id"], node["node_id"])
            self.assertEqual(computing["nodes"][0]["run"]["state"], "computing")
            schedules = list(Path(directory).rglob("schedule_*.json"))
            self.assertEqual(len(schedules), 1)
            payload = json.loads(schedules[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "aster-factor-schedule-v1")
            self.assertEqual(
                payload["entries"][0]["selected_groups"],
                node["rounds"][0]["selected_groups"],
            )
            portfolio_schedules = list(Path(directory).rglob("portfolio_schedule_*.json"))
            self.assertEqual(len(portfolio_schedules), 1)
            portfolio_payload = json.loads(
                portfolio_schedules[0].read_text(encoding="utf-8")
            )
            self.assertEqual(portfolio_payload["schema"], "aster-portfolio-schedule-v1")
            self.assertEqual(
                portfolio_payload["entries"][0]["selected_profile_id"], "balanced"
            )
            self.assertEqual(
                portfolio_payload["entries"][0]["round_id"],
                payload["entries"][0]["round_id"],
            )

    def test_automatic_mode_queues_quarterly_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ReplayService(session_root=Path(directory), launch_runs=False)
            session = service.create_session(automatic=True)
            self.assertEqual(session["automation_mode"], "automatic")
            self.assertEqual(session["automation_state"], "deciding")
            self.assertTrue(all(node["accepted_round_id"] is None for node in session["nodes"]))
            self.assertTrue(all(len(node["portfolio_rounds"]) == 1 for node in session["nodes"]))
            self.assertEqual(len(session["nodes"]), 20)

    def test_forecaster_switches_features_by_signal(self) -> None:
        dates = pd.date_range("2024-01-01", periods=14, freq="D")
        columns = ["A", "B", "C"]
        close = pd.DataFrame(
            np.linspace(10, 18, len(dates))[:, None] * np.array([[1.0, 1.1, 0.9]]),
            index=dates,
            columns=columns,
        )
        features = {
            "alpha_a": close.pct_change().fillna(0.0),
            "alpha_b": close.rolling(2).mean().fillna(close),
        }
        signal_dates = [dates[8], dates[10]]
        result = WalkForwardRidgeForecaster(
            horizon_days=1, training_sessions=5, minimum_samples=1
        ).fit_predict(
            features=features,
            close=close,
            signal_dates=signal_dates,
            feature_names_by_signal={
                signal_dates[0]: ["alpha_a"],
                signal_dates[1]: ["alpha_b"],
            },
        )
        self.assertEqual(result.diagnostics["active_features"].tolist(), ["alpha_a", "alpha_b"])


if __name__ == "__main__":
    unittest.main()
