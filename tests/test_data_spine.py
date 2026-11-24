import tempfile
import unittest
from pathlib import Path

import pandas as pd

from aster_data.akshare_market import normalize_akshare_daily
from aster_data.ic_futures import build_lagged_continuous
from aster_data.io import instrument_from_code
from aster_data.pit_universe import apply_official_adjustments, snapshots_to_intervals
from aster_portfolio.risk import estimate_risk


class DataSpineTest(unittest.TestCase):
    def test_symbol_normalization(self) -> None:
        self.assertEqual(instrument_from_code("600519.ss"), "SH600519")
        self.assertEqual(instrument_from_code("000001.SZ"), "SZ000001")
        self.assertEqual(instrument_from_code("430047"), "BJ430047")

    def test_akshare_daily_contract(self) -> None:
        frame = pd.DataFrame(
            {
                "日期": ["2024-01-03", "2024-01-02"],
                "开盘": [10.1, 10.0],
                "收盘": [10.2, 10.1],
                "最高": [10.3, 10.2],
                "最低": [10.0, 9.9],
                "成交量": [100, 90],
                "成交额": [1020, 900],
                "振幅": [3.0, 3.0],
                "涨跌幅": [1.0, 1.0],
                "涨跌额": [0.1, 0.1],
                "换手率": [0.5, 0.4],
            }
        )
        result = normalize_akshare_daily(frame, instrument="600519", adjustment="hfq")
        self.assertEqual(result["instrument"].unique().tolist(), ["SH600519"])
        self.assertEqual(result["date"].tolist(), ["2024-01-02", "2024-01-03"])
        self.assertEqual(result["adjustment"].unique().tolist(), ["hfq"])

    def test_official_universe_overlay_and_intervals(self) -> None:
        snapshots = pd.DataFrame(
            {
                "requested_as_of": pd.to_datetime(
                    ["2024-01-05", "2024-01-12", "2024-01-19"]
                ),
                "snapshot_date": pd.to_datetime(
                    ["2024-01-05", "2024-01-12", "2024-01-19"]
                ),
                "instrument": ["SH600000", "SH600000", "SH600000"],
                "snapshot_file": ["a", "b", "c"],
            }
        )
        adjustments = pd.DataFrame(
            {
                "effective_date": ["2024-01-12"],
                "instrument": ["000001.SZ"],
                "action": ["add"],
                "source_id": ["official:test"],
            }
        )
        overlaid = apply_official_adjustments(snapshots, adjustments)
        intervals = snapshots_to_intervals(overlaid, requested_end=pd.Timestamp("2024-01-31"))
        added = intervals.loc[intervals["instrument"] == "SZ000001"].iloc[0]
        self.assertEqual(added["effective_start"], pd.Timestamp("2024-01-12"))
        self.assertEqual(added["effective_end"], pd.Timestamp("2024-01-31"))

    def test_ic_selection_is_lagged(self) -> None:
        contracts = pd.DataFrame(
            [
                ("2024-01-02", "IC2401", 100, 1000, 5000),
                ("2024-01-02", "IC2402", 101, 500, 1000),
                ("2024-01-03", "IC2401", 102, 300, 1000),
                ("2024-01-03", "IC2402", 103, 1500, 6000),
                ("2024-01-04", "IC2401", 104, 100, 500),
                ("2024-01-04", "IC2402", 106, 1600, 7000),
            ],
            columns=["date", "contract", "close", "volume", "open_interest"],
        )
        contracts["pre_settle"] = contracts["close"] - 1
        contracts["settle"] = contracts["close"]
        result = build_lagged_continuous(contracts, multiplier=200, margin_rate=0.12)
        self.assertEqual(result.loc[1, "contract"], "IC2401")
        self.assertTrue(result.loc[1, "roll"])
        self.assertEqual(result.loc[2, "contract"], "IC2402")
        self.assertAlmostEqual(result.loc[2, "hedge_return"], 106 / 103 - 1)

    def test_sparse_asset_risk_is_conservatively_imputed(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=80)
        stocks = pd.DataFrame(
            {
                "full": [0.001 * ((index % 5) - 2) for index in range(80)],
                "short": [None] * 70 + [0.01] * 10,
            },
            index=dates,
        )
        benchmark = pd.Series(
            [0.0005 * ((index % 7) - 3) for index in range(80)], index=dates
        )
        result = estimate_risk(stocks, benchmark, window=80, minimum_observations=60)
        self.assertEqual(result.betas["short"], 1.0)
        self.assertIn("short", result.imputed_assets)
        self.assertGreater(
            result.covariance.loc["short", "short"],
            result.covariance.loc["full", "full"],
        )


if __name__ == "__main__":
    unittest.main()
