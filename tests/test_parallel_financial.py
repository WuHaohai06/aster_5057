import tempfile
import unittest
from pathlib import Path

import pandas as pd

from aster_data.parallel_financial import discover_instruments


class DiscoverInstrumentsTest(unittest.TestCase):
    def test_discovers_unique_symbols_from_snapshot_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame({"instrument": ["SH600000", "SZ000001"]}).to_csv(
                root / "snapshot_requested_2024-01-01.csv", index=False
            )
            pd.DataFrame({"instrument": ["SH600000", "SZ000002"]}).to_csv(
                root / "snapshot_requested_2024-01-08.csv", index=False
            )
            self.assertEqual(
                discover_instruments(root),
                ["SH600000", "SZ000001", "SZ000002"],
            )


if __name__ == "__main__":
    unittest.main()
