from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aster_console.api import app, build_snapshot, snapshot_digest  # noqa: E402


class ConsoleApiTest(unittest.TestCase):
    def test_read_only_routes_and_stable_digest(self) -> None:
        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("GET", "/api/health"), routes)
        self.assertIn(("GET", "/api/snapshot"), routes)
        self.assertIn(("GET", "/api/events"), routes)
        self.assertFalse(any(method in {"POST", "PUT", "PATCH", "DELETE"} for method, _ in routes))

        snapshot = build_snapshot()
        later = copy.deepcopy(snapshot)
        later["meta"]["generatedAt"] = "2099-01-01T00:00:00+08:00"
        self.assertEqual(snapshot_digest(snapshot), snapshot_digest(later))


if __name__ == "__main__":
    unittest.main()
