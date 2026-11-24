import tempfile
import unittest
from pathlib import Path

import pandas as pd

from aster_quantalpha.data_adapter import (
    QuantaAlphaDataAdapter,
    to_qlib_instrument,
    to_trading_date,
)


class QuantaAlphaAdapterTest(unittest.TestCase):
    def test_symbol_mapping(self) -> None:
        self.assertEqual(to_qlib_instrument("600519.SS"), "SH600519")
        self.assertEqual(to_qlib_instrument("000001.SZ"), "SZ000001")
        self.assertEqual(to_qlib_instrument("SH600000"), "SH600000")

    def test_adjustment_and_returns_are_per_instrument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            pd.DataFrame(
                {
                    "symbol": ["600000.SS", "600000.SS", "000001.SZ", "000001.SZ"],
                    "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
                    "open": [10, 11, 20, 18],
                    "high": [11, 12, 21, 19],
                    "low": [9, 10, 19, 17],
                    "close": [10, 11, 20, 18],
                    "volume": [100, 110, 200, 180],
                    "adjclose": [5, 5.5, 20, 18],
                }
            ).to_csv(path, index=False)
            panel = QuantaAlphaDataAdapter.load_market_panel([path])
            self.assertEqual(panel.index.names, ["datetime", "instrument"])
            self.assertEqual(panel.loc[(pd.Timestamp("2024-01-02"), "SH600000"), "$open"], 5)
            self.assertAlmostEqual(
                panel.loc[(pd.Timestamp("2024-01-03"), "SH600000"), "$return"],
                0.1,
            )
            self.assertEqual(panel.loc[(pd.Timestamp("2024-01-02"), "SZ000001"), "$return"], 0)

    def test_timezone_suffix_does_not_shift_exchange_date(self) -> None:
        parsed = to_trading_date(
            pd.Series(["2024-01-02 00:00:00+08:00", "2024-01-03T15:00:00Z"])
        )
        self.assertEqual(parsed.tolist(), [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")])
        self.assertIsNone(parsed.dt.tz)


if __name__ == "__main__":
    unittest.main()
