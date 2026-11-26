from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from aster_data.factor_library import (
    FactorArtifact,
    FactorCatalog,
    FactorRecord,
    LifecycleStatus,
    _canonical_digest,
    _merge_previous_record,
    _quanta_metric,
    _write_catalog,
    evaluate_quantaalpha_candidates,
    load_catalog,
    load_factor_values,
    set_factor_status,
    validate_factor_library,
)
from aster_data.io import sha256_file


class FactorLibraryTest(unittest.TestCase):
    def test_quanta_metric_accepts_legacy_key_spellings(self) -> None:
        metrics = {"IC": 0.01, "Rank IC": 0.03, "Rank ICIR": 0.2}
        self.assertEqual(_quanta_metric(metrics, "ic"), 0.01)
        self.assertEqual(_quanta_metric(metrics, "rank_ic", "rank ic"), 0.03)
        self.assertEqual(_quanta_metric(metrics, "rank_ic_ir", "rank icir"), 0.2)

    def test_rebuild_preserves_evaluated_diagnostics_for_same_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self._library(root)
            base = load_catalog(output / "catalog.json").factors[0]
            for origin in ("quantaalpha", "filing_text_llm"):
                with self.subTest(origin=origin):
                    previous = base.model_copy(
                        update={
                            "origin": origin,
                            "lifecycle_status": LifecycleStatus.VALIDATED,
                            "research_eligible": True,
                            "diagnostics": {"rank_ic_mean": 0.02, "ic": 0.01},
                        }
                    )
                    refreshed = base.model_copy(
                        update={"origin": origin, "diagnostics": {"ic": 0.03}}
                    )
                    merged = _merge_previous_record(refreshed, previous)
                    self.assertEqual(merged.lifecycle_status, LifecycleStatus.VALIDATED)
                    self.assertTrue(merged.research_eligible)
                    self.assertEqual(merged.diagnostics["rank_ic_mean"], 0.02)
                    self.assertEqual(merged.diagnostics["ic"], 0.03)

    def _library(self, root: Path) -> Path:
        values = root / "data" / "factor.parquet"
        values.parent.mkdir(parents=True)
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-02"]),
                "available_at": pd.to_datetime(["2024-01-02"]),
                "instrument": ["SH600000"],
                "factor_id": ["demo_factor"],
                "factor_group": ["demo"],
                "value": [1.0],
                "origin": ["test"],
                "source_id": ["test:one"],
                "version": ["v1"],
            }
        )
        frame.to_parquet(values, index=False)
        record = FactorRecord(
            factor_id="demo_factor",
            display_name="Demo Factor",
            factor_group="demo",
            family="price_volume",
            origin="test",
            version="v1",
            lifecycle_status=LifecycleStatus.CANDIDATE,
            status_reason="test candidate",
            expression="close",
            description="test factor",
            implementation_ref="tests/test_factor_library.py",
            pit_compliant=True,
            research_eligible=False,
            demo_eligible=True,
            artifact=FactorArtifact(
                path="data/factor.parquet",
                format="canonical_long_parquet",
                sha256=sha256_file(values),
                rows=1,
                instruments=1,
                first_date=pd.Timestamp("2024-01-02").date(),
                last_date=pd.Timestamp("2024-01-02").date(),
            ),
        )
        output = root / "library"
        catalog = FactorCatalog(
            generated_at=datetime.now().astimezone(),
            catalog_digest=_canonical_digest([record]),
            factors=[record],
        )
        _write_catalog(catalog, output)
        return output

    def test_catalog_validates_and_loads_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self._library(root)
            result = validate_factor_library(
                project_root=root, catalog_path=output / "catalog.json"
            )
            self.assertTrue(result["passed"], result["errors"])
            values = load_factor_values(
                project_root=root,
                catalog_path=output / "catalog.json",
                factor_id="demo_factor",
            )
            self.assertEqual(len(values), 1)

    def test_lifecycle_transition_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = self._library(Path(directory))
            catalog = set_factor_status(
                output_root=output,
                factor_id="demo_factor",
                new_status=LifecycleStatus.DEMO_SELECTED,
                reason="selected for course demo",
                actor="unit-test",
            )
            self.assertEqual(catalog.factors[0].lifecycle_status, LifecycleStatus.DEMO_SELECTED)
            self.assertTrue((output / "lifecycle_events.json").exists())

    def test_quanta_evaluation_promotes_ready_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self._library(root)
            catalog = load_catalog(output / "catalog.json")
            record = catalog.factors[0].model_copy(
                update={"origin": "quantaalpha", "factor_id": "quanta_demo"}
            )
            catalog = FactorCatalog(
                generated_at=datetime.now().astimezone(),
                catalog_digest=_canonical_digest([record]),
                factors=[record],
            )
            _write_catalog(catalog, output)
            diagnostics = {
                "label_horizon_days": 20,
                "factors": [{
                    "factor_id": "quanta_demo",
                    "observed_at": "2024-12-31",
                    "latest_label_date": "2024-12-31",
                    "observations": 100,
                    "coverage": 0.9,
                    "rank_ic_mean": 0.02,
                    "rank_ic_ir": 0.3,
                    "rank_ic_positive_fraction": 0.6,
                    "turnover": 0.1,
                    "max_abs_correlation": 0.2,
                    "yearly_rank_ic": {"2024": 0.02},
                    "decay_rank_ic": {"20": 0.02},
                    "warnings": [],
                }],
            }
            with patch(
                "aster_data.factor_library.evaluate_factors",
                return_value=({"factors": []}, diagnostics),
            ):
                result = evaluate_quantaalpha_candidates(
                    project_root=root,
                    catalog_path=output / "catalog.json",
                    market_path=root / "market.parquet",
                    evidence_root=root / "evidence",
                    as_of="2024-12-31",
                )
            updated = load_catalog(output / "catalog.json").factors[0]
            self.assertEqual(result["promoted"], ["quanta_demo"])
            self.assertEqual(updated.lifecycle_status, LifecycleStatus.VALIDATED)
            self.assertTrue(updated.research_eligible)
            self.assertEqual(updated.diagnostics["rank_ic_mean"], 0.02)
            self.assertTrue((output / "lifecycle_events.json").exists())


if __name__ == "__main__":
    unittest.main()
