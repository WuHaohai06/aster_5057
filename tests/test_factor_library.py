from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from aster_data.factor_library import (
    FactorArtifact,
    FactorCatalog,
    FactorRecord,
    LifecycleStatus,
    _canonical_digest,
    _write_catalog,
    load_factor_values,
    set_factor_status,
    validate_factor_library,
)
from aster_data.io import sha256_file


class FactorLibraryTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
