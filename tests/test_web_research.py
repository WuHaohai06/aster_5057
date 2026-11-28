from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aster_console.web_research import DeepSeekWebResearchCollector  # noqa: E402


class StaticSearchCollector(DeepSeekWebResearchCollector):
    def __init__(self) -> None:
        super().__init__(api_key="test-key", keep_per_query=3)

    def _search(self, query: str):
        return [
            {
                "title": "Eligible historical source",
                "url": "https://example.com/eligible",
                "snippet": "Historical evidence",
                "summary": "Historical evidence available before the cutoff.",
                "site_name": "Example",
                "date": "2024-03-01T00:00:00Z",
                "authority": 3,
                "rerank_score": 2.0,
            },
            {
                "title": "Future source",
                "url": "https://example.com/future",
                "snippet": "Future evidence",
                "summary": "This source was published after the cutoff.",
                "site_name": "Example",
                "date": "2025-01-01T00:00:00Z",
                "authority": 2,
                "rerank_score": 1.8,
            },
            {
                "title": "Undated source",
                "url": "https://example.com/undated",
                "snippet": "No date",
                "summary": "This source has no publication date.",
                "site_name": "Example",
                "date": None,
                "authority": 1,
                "rerank_score": 1.0,
            },
        ]


class WebResearchTest(unittest.TestCase):
    def test_research_mode_enforces_publication_cutoff(self) -> None:
        result = StaticSearchCollector().collect(
            node_id="factor-council-2024-06-30",
            decision_at=date(2024, 6, 30),
            input_cutoff=date(2024, 6, 30),
            mode="research",
            candidate_groups=["conventional_low_vol"],
        )
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(len(result["rejected"]), 2)
        self.assertTrue(result["accepted"][0]["pit_eligible"])
        self.assertTrue(result["evidence_digest"])

    def test_showcase_mode_keeps_hindsight_with_disclosure(self) -> None:
        result = StaticSearchCollector().collect(
            node_id="factor-council-2024-06-30",
            decision_at=date(2024, 6, 30),
            input_cutoff=date(2024, 6, 30),
            mode="showcase_reenactment",
            candidate_groups=["conventional_low_vol"],
        )
        self.assertEqual(len(result["accepted"]), 2)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("after", result["disclosure"])


if __name__ == "__main__":
    unittest.main()
