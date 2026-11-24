from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from aster_data.factor_store import build_financial_factors, ingest_factor_file
from aster_data.filing_text_factors import build_filing_text_factors
from aster_portfolio.research_ops import build_experiment_matrix, verify_research_inputs


def test_financial_factor_builder_preserves_disclosure_date(tmp_path: Path) -> None:
    pit = tmp_path / "pit"
    pit.mkdir()
    pd.DataFrame([
        {"instrument": "600000.ss", "date": "2024-04-01", "period": "2023-12-31", "value": 0.1, "field": "roeWa", "endpoint": "profit", "source": "test"},
        {"instrument": "600000.ss", "date": "2024-04-01", "period": "2023-12-31", "value": 0.2, "field": "YOYNI", "endpoint": "growth", "source": "test"},
    ]).to_csv(pit / "one.csv", index=False)
    result = build_financial_factors(pit_root=pit, output_root=tmp_path / "out")
    frame = pd.read_parquet(result["path"])
    assert set(frame["instrument"]) == {"SH600000"}
    assert set(frame["factor_id"]) == {"fin_roewa", "fin_yoyni"}
    assert (frame["available_at"] == pd.Timestamp("2024-04-01")).all()


def test_factor_ingest_rejects_future_availability(tmp_path: Path) -> None:
    source = tmp_path / "factor.csv"
    pd.DataFrame({
        "date": ["2024-01-02"], "available_at": ["2024-01-03"],
        "instrument": ["600000.ss"], "value": [1.0], "factor_id": ["bad"],
    }).to_csv(source, index=False)
    with pytest.raises(ValueError, match="available_at"):
        ingest_factor_file(input_path=source, output_root=tmp_path / "out")


def test_filing_text_factor_keeps_source_evidence(tmp_path: Path) -> None:
    parsed = tmp_path / "parsed" / "600000" / "hash"
    parsed.mkdir(parents=True)
    (parsed / "document.json").write_text(json.dumps({
        "available_at": "2024-04-01T00:00:00+08:00", "instrument": "SH600000",
        "source_sha256": "a" * 64, "quality": "text_extracted",
        "pages": [{"page": 1, "text": "经营稳健增长，但存在市场波动风险。"}],
    }, ensure_ascii=False), encoding="utf-8")
    result = build_filing_text_factors(
        parsed_root=tmp_path / "parsed", output_root=tmp_path / "out"
    )
    frame = pd.read_parquet(result["path"])
    assert len(frame) == 3
    assert set(frame["source_id"]) == {"filing:" + "a" * 64}
    assert (tmp_path / "out" / "evidence" / (("a" * 64) + ".deterministic.json")).exists()


def test_experiment_matrix_keeps_fixed_baseline(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "version": "v1", "universe": "CSI500_PIT", "factors": [
            {"factor_id": "r", "factor_group": "conventional_reversal", "approval_status": "approved"},
            {"factor_id": "l", "factor_group": "conventional_low_vol", "approval_status": "approved"},
            {"factor_id": "q", "factor_group": "quanta", "approval_status": "approved"},
        ],
    }), encoding="utf-8")
    matrix = build_experiment_matrix(registry)
    marginal = next(item for item in matrix["experiments"] if item["experiment_id"] == "baseline_plus_quanta")
    assert marginal["groups"] == ["conventional_reversal", "conventional_low_vol", "quanta"]


def test_verifier_detects_factor_lookahead(tmp_path: Path) -> None:
    market_path = tmp_path / "market.parquet"
    pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"]), "instrument": ["SH600000"],
        "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
        "volume": [100.0], "csi500_member": [True],
    }).to_parquet(market_path, index=False)
    factor_path = tmp_path / "factor.parquet"
    pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"]), "available_at": pd.to_datetime(["2024-01-03"]),
        "instrument": ["SH600000"], "factor_id": ["x"], "value": [1.0],
    }).to_parquet(factor_path, index=False)
    result = verify_research_inputs(market_path=market_path, factor_paths=[factor_path])
    assert not result["passed"]
    assert next(item for item in result["checks"] if item["check"].endswith(":no_future"))["passed"] is False
