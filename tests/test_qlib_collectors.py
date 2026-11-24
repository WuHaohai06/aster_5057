import tempfile
import unittest
from pathlib import Path

import pandas as pd

from aster_data.qlib_collectors import QlibCollectorAdapter


class ArtifactTest(unittest.TestCase):
    def test_write_artifact_is_deterministic(self) -> None:
        frame = pd.DataFrame({"date": ["2024-01-02"], "value": [1.0]})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.csv"
            first = QlibCollectorAdapter._write_artifact(frame, target, {"dataset": "test"})
            second = QlibCollectorAdapter._write_artifact(frame, target, {"dataset": "test"})
            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(first.row_count, 1)
            self.assertTrue(first.metadata_path.exists())


if __name__ == "__main__":
    unittest.main()

