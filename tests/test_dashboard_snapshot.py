from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_dashboard_snapshot", ROOT / "scripts" / "export_dashboard_snapshot.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DashboardSnapshotTest(unittest.TestCase):
    def test_snapshot_is_sanitised_and_has_frontend_contract(self) -> None:
        snapshot = MODULE.build_snapshot()
        self.assertEqual(snapshot["meta"]["schema"], "aster-console-snapshot-v2")
        self.assertTrue(snapshot["pipeline"])
        self.assertIn("factors", snapshot)
        self.assertIn("factorCouncil", snapshot)
        self.assertEqual(len(snapshot["filings"]["years"]), 6)
        self.assertEqual(snapshot["filings"]["year_start"], 2020)
        self.assertEqual(snapshot["filings"]["year_end"], 2025)
        self.assertEqual(
            snapshot["filings"]["score_total"],
            snapshot["filings"]["documents_total"],
        )
        self.assertIn(snapshot["meta"]["mode"], {"research", "showcase_reenactment"})
        self.assertIn("mode", snapshot["factorCouncil"]["decision"])
        serialised = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn(str(ROOT), serialised)
        self.assertIsNone(re.search(r"sk-[a-z0-9]{20,}", serialised.lower()))


if __name__ == "__main__":
    unittest.main()
