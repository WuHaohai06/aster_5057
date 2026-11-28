from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from aster_council import refresh as refresh_module
from aster_data.factor_library import (
    FactorArtifact,
    FactorCatalog,
    FactorRecord,
    LifecycleStatus,
    _canonical_digest,
    _write_catalog,
    load_catalog,
    rebase_market_factor_artifacts,
)


def _record(factor_id: str, origin: str, artifact_path: str) -> FactorRecord:
    return FactorRecord(
        factor_id=factor_id,
        display_name=factor_id,
        factor_group=factor_id,
        family="price_volume" if origin == "aster_deterministic_baseline" else "style",
        origin=origin,
        version="v1",
        lifecycle_status=LifecycleStatus.VALIDATED,
        status_reason="test",
        expression="close",
        description="test factor",
        implementation_ref="tests",
        pit_compliant=True,
        research_eligible=True,
        demo_eligible=True,
        artifact=FactorArtifact(
            path=artifact_path, format="canonical_long_parquet", sha256="0" * 64,
            rows=2, instruments=2,
        ),
        diagnostics={"observed_at": "2025-12-31", "rank_ic_mean": 0.01},
    )


class RebaseMarketArtifactsTest(unittest.TestCase):
    def test_conventional_records_point_at_fresh_market_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parquet = root / "market_factors.parquet"
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-09-29", "2026-09-30"] * 2),
                    "instrument": ["SH600000", "SH600000", "SZ000001", "SZ000001"],
                    "value": [0.1, 0.2, 0.3, 0.4],
                    "factor_id": ["conventional_low_vol"] * 2 + ["conventional_reversal"] * 2,
                    "factor_group": ["conventional_low_vol"] * 2 + ["conventional_reversal"] * 2,
                    "available_at": pd.to_datetime(["2026-09-29", "2026-09-30"] * 2),
                    "origin": ["aster_deterministic_baseline"] * 4,
                    "source_id": ["market:test"] * 4,
                    "version": ["aster-pv-baseline-v1"] * 4,
                }
            ).to_parquet(parquet, index=False)
            catalog = FactorCatalog(
                generated_at=datetime.now(timezone.utc),
                catalog_digest=_canonical_digest(
                    [
                        _record("conventional_low_vol", "aster_deterministic_baseline", "old.parquet"),
                        _record("beta_instability", "aster_style_factors", "style.parquet"),
                    ]
                ),
                factors=[
                    _record("conventional_low_vol", "aster_deterministic_baseline", "old.parquet"),
                    _record("beta_instability", "aster_style_factors", "style.parquet"),
                ],
            )
            _write_catalog(catalog, root)

            rebase_market_factor_artifacts(
                catalog_path=root / "catalog.json", market_path=parquet, project_root=root
            )

            updated = {item.factor_id: item for item in load_catalog(root / "catalog.json").factors}
            self.assertEqual(updated["conventional_low_vol"].artifact.path, "market_factors.parquet")
            self.assertTrue(updated["conventional_low_vol"].artifact.shared_file)
            self.assertEqual(updated["conventional_low_vol"].artifact.rows, 2)
            self.assertEqual(updated["beta_instability"].artifact.path, "style.parquet")


class RefreshOrchestrationTest(unittest.TestCase):
    def test_refresh_builds_packet_at_cutoff_with_current_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = root / "quarterly"
            library_root = root / "library"
            library_root.mkdir()
            (library_root / "catalog.json").write_text(
                json.dumps({"schema_version": "v1", "generated_at": "2026-01-01T00:00:00+00:00",
                            "catalog_digest": "d", "factors": []}),
                encoding="utf-8",
            )
            policy = root / "policy.json"
            policy.write_text("{}", encoding="utf-8")
            cutoff = "2026-09-30"
            calls: dict[str, object] = {}

            fake_catalog = SimpleNamespace(
                factors=[
                    SimpleNamespace(origin="aster_deterministic_baseline", factor_group="conventional_low_vol"),
                    SimpleNamespace(origin="aster_style_factors", factor_group="style_beta"),
                ],
                catalog_digest="digest",
            )

            def fake_market_factors(*, market_path, output_path, as_of=None):
                calls["market_as_of"] = as_of
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"parquet")
                return {"rows": 2, "factor_ids": [], "path": str(output_path), "sha256": "0"}

            def fake_rebase(*, catalog_path, market_path, project_root):
                calls["rebase_market_path"] = Path(market_path).name

            def fake_evaluate(*, project_root, catalog_path, market_path, evidence_root, as_of,
                      origins=("quantaalpha",), groups=None, **kwargs):
                calls.setdefault("evaluate_as_of", []).append(as_of)
                calls.setdefault("evaluate_groups", []).append(groups)
                return {"evaluated": 1}

            def fake_export(*, catalog_path, output_root, mode="research", groups=None):
                calls["export_mode"] = mode
                Path(output_root).mkdir(parents=True, exist_ok=True)
                (Path(output_root) / "factor_registry.json").write_text("{}", encoding="utf-8")
                (Path(output_root) / "factor_diagnostics.json").write_text(
                    json.dumps({"label_horizon_days": 20, "factors": [
                        {"factor_id": "conventional_low_vol", "observed_at": cutoff}
                    ]}),
                    encoding="utf-8",
                )
                return {"registry_factors": 1, "diagnostic_factors": 1, "missing_diagnostics": []}

            def fake_market_context(*, market_path, as_of, output_path):
                calls["market_state_as_of"] = as_of
                Path(output_path).write_text(json.dumps({"as_of_close": as_of}), encoding="utf-8")
                return {"as_of_close": as_of}

            class FakeBuilder:
                def build_from_files(self, **kwargs):
                    calls["packet_decision_at"] = kwargs["decision_at"].isoformat()
                    calls["packet_market"] = Path(kwargs["market_path"]).name
                    return SimpleNamespace(
                        packet_digest="packet-digest",
                        factor_groups=[SimpleNamespace(group_id="conventional_low_vol")],
                        excluded_factors={"conventional_momentum": "stale"},
                    )

            with patch.object(refresh_module, "build_market_factors", fake_market_factors), \
                 patch.object(refresh_module, "rebase_market_factor_artifacts", fake_rebase), \
                 patch.object(refresh_module, "evaluate_quantaalpha_candidates", fake_evaluate), \
                 patch.object(refresh_module, "export_council_inputs", fake_export), \
                 patch.object(refresh_module, "build_market_context", fake_market_context), \
                 patch.object(refresh_module, "load_catalog", lambda path: fake_catalog), \
                 patch.object(refresh_module, "DecisionPacketBuilder", FakeBuilder), \
                 patch.object(refresh_module, "write_packet",
                              lambda packet, path: Path(path).write_text("{}", encoding="utf-8")):
                summary = refresh_module.refresh_quarter_evidence(
                    cutoff=cutoff, output_root=output_root, project_root=root,
                    market_path=root / "market.parquet", policy_path=policy,
                    library_root=library_root,
                )

            self.assertEqual(calls["market_as_of"], cutoff)
            self.assertEqual(calls["rebase_market_path"], "market_factors.parquet")
            self.assertEqual(set(calls["evaluate_as_of"]), {cutoff})
            self.assertEqual(calls["packet_decision_at"], cutoff)
            self.assertEqual(calls["packet_market"], "market_state.json")
            self.assertEqual(summary["diagnostic_observed_at"], [cutoff])
            self.assertTrue(Path(summary["packet_path"]).exists())
            self.assertTrue((output_root / cutoff / "refresh.json").exists())

    def test_evaluation_chunks_split_quantaalpha_by_group(self) -> None:
        catalog = SimpleNamespace(factors=[
            SimpleNamespace(origin="aster_deterministic_baseline", factor_group="conventional_low_vol"),
            SimpleNamespace(origin="aster_style_factors", factor_group="style_beta"),
            SimpleNamespace(origin="quantaalpha", factor_group="quanta_pv_a01"),
            SimpleNamespace(origin="quantaalpha", factor_group="quanta_pv_a03"),
        ])
        chunks = refresh_module._evaluation_chunks(catalog)
        self.assertEqual([name for name, _, _ in chunks], ["conventional", "style", "quanta-quanta_pv_a01", "quanta-quanta_pv_a03"])
        self.assertEqual(chunks[2][2], {"quanta_pv_a01"})


if __name__ == "__main__":
    unittest.main()
