import tempfile
import unittest
from pathlib import Path

import pandas as pd

from aster_quantalpha.data_adapter import (
    MARKET_RETURN_COLUMN,
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

    def test_market_return_is_broadcast_by_date_without_backfill(self) -> None:
        index = pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2024-01-02"), "SH000905"),
                (pd.Timestamp("2024-01-02"), "SH600000"),
                (pd.Timestamp("2024-01-03"), "SH600000"),
                (pd.Timestamp("2024-01-02"), "SZ000001"),
            ],
            names=["datetime", "instrument"],
        )
        panel = pd.DataFrame(
            {
                "$open": [1.0] * 4,
                "$high": [1.0] * 4,
                "$low": [1.0] * 4,
                "$close": [1.0] * 4,
                "$volume": [1.0] * 4,
                "$return": [0.012, 0.02, -0.01, 0.03],
            },
            index=index,
        )
        result = QuantaAlphaDataAdapter.attach_market_return(panel)
        self.assertNotIn("SH000905", result.index.get_level_values("instrument"))
        self.assertEqual(
            result.loc[(pd.Timestamp("2024-01-02"), "SH600000"), MARKET_RETURN_COLUMN],
            0.012,
        )
        self.assertEqual(
            result.loc[(pd.Timestamp("2024-01-02"), "SZ000001"), MARKET_RETURN_COLUMN],
            0.012,
        )
        self.assertTrue(
            pd.isna(
                result.loc[
                    (pd.Timestamp("2024-01-03"), "SH600000"),
                    MARKET_RETURN_COLUMN,
                ]
            )
        )
        self.assertLess(
            result.columns.get_loc(MARKET_RETURN_COLUMN),
            result.columns.get_loc("$return"),
        )


if __name__ == "__main__":
    unittest.main()
