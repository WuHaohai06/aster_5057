from __future__ import annotations

import pandas as pd

from aster_data.factor_input_download import (
    discover_instruments,
    normalize_industry,
    normalize_statement,
    normalize_valuation,
)


def test_discover_instruments_deduplicates(tmp_path):
    path = tmp_path / "intervals.parquet"
    pd.DataFrame({"instrument": ["SH600062", "600062.SH", "SZ000001"]}).to_parquet(
        path, index=False
    )
    assert discover_instruments(path) == ["SH600062", "SZ000001"]


def test_normalize_valuation_filters_and_adds_availability():
    source = pd.DataFrame(
        {
            "数据日期": ["2016-01-01", "2024-01-02"],
            "当日收盘价": [10, 11],
            "当日涨跌幅": [0, 1],
            "总市值": [100, 110],
            "流通市值": [80, 90],
            "总股本": [10, 10],
            "流通股本": [8, 8],
            "PE(TTM)": [12, 13],
            "PE(静)": [14, 15],
            "市净率": [2, 2.1],
            "PEG值": [1, 1.1],
            "市现率": [8, 9],
            "市销率": [3, 3.1],
        }
    )
    result = normalize_valuation(
        source, instrument="600062.SH", start="2020-01-01", end="2025-01-01"
    )
    assert result["instrument"].tolist() == ["SH600062"]
    assert result["total_market_cap"].tolist() == [110]
    assert result["available_at"].equals(result["date"])


def test_normalize_statement_uses_notice_date_for_pit():
    source = pd.DataFrame(
        {
            "REPORT_DATE": ["2023-12-31", "2024-12-31"],
            "NOTICE_DATE": ["2024-03-30", "2026-03-30"],
            "TOTAL_ASSETS": [100, 120],
        }
    )
    result = normalize_statement(
        source, instrument="SH600062", start="2016-11-24", end="2025-12-31"
    )
    assert len(result) == 1
    assert result["available_at"].iloc[0] == pd.Timestamp("2024-03-30")


def test_normalize_industry_uses_change_date():
    source = pd.DataFrame(
        {
            "证券代码": ["600062"],
            "变更日期": ["2021-12-17"],
            "分类标准": ["test"],
            "行业编码": ["35202020"],
        }
    )
    result = normalize_industry(source, instrument="SH600062")
    assert result["available_at"].iloc[0] == pd.Timestamp("2021-12-17")
