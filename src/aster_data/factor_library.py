"""Unified factor catalog, lifecycle management and canonical value materialization."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aster_portfolio.factors import PRICE_VOLUME_FACTOR_DEFINITIONS

from .factor_evidence import evaluate_factors
from .factor_store import FACTOR_COLUMNS
from .io import instrument_from_code, sha256_file, write_json_atomic


CATALOG_SCHEMA_VERSION = "aster-factor-library-v2"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LifecycleStatus(str, Enum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    COUNCIL_APPROVED = "council_approved"
    DEMO_SELECTED = "demo_selected"
    RETIRED = "retired"


ALLOWED_TRANSITIONS = {
    LifecycleStatus.CANDIDATE: {
        LifecycleStatus.VALIDATED,
        LifecycleStatus.DEMO_SELECTED,
        LifecycleStatus.RETIRED,
    },
    LifecycleStatus.VALIDATED: {
        LifecycleStatus.COUNCIL_APPROVED,
        LifecycleStatus.DEMO_SELECTED,
        LifecycleStatus.RETIRED,
    },
    LifecycleStatus.COUNCIL_APPROVED: {
        LifecycleStatus.VALIDATED,
        LifecycleStatus.DEMO_SELECTED,
        LifecycleStatus.RETIRED,
    },
    LifecycleStatus.DEMO_SELECTED: {
        LifecycleStatus.CANDIDATE,
        LifecycleStatus.VALIDATED,
        LifecycleStatus.COUNCIL_APPROVED,
        LifecycleStatus.RETIRED,
    },
    LifecycleStatus.RETIRED: {LifecycleStatus.CANDIDATE},
}


class FactorArtifact(StrictModel):
    path: str
    format: str
    sha256: str
    rows: int = Field(ge=0)
    instruments: int = Field(ge=0)
    first_date: date | None = None
    last_date: date | None = None
    shared_file: bool = False
    source_path: str | None = None
    source_sha256: str | None = None


class FactorRecord(StrictModel):
    factor_id: str
    display_name: str
    factor_group: str
    family: str
    origin: str
    version: str
    lifecycle_status: LifecycleStatus
    status_reason: str
    expression: str
    description: str
    economic_hypothesis: str = ""
    mechanism_explanation: str = ""
    expected_direction: str = ""
    falsification_criteria: list[str] = Field(default_factory=list)
    mechanism_source: str = ""
    implementation_ref: str
    pit_compliant: bool
    research_eligible: bool
    demo_eligible: bool
    artifact: FactorArtifact
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class FactorCatalog(StrictModel):
    schema_version: str = CATALOG_SCHEMA_VERSION
    generated_at: datetime
    catalog_digest: str
    factors: list[FactorRecord]

    @model_validator(mode="after")
    def unique_ids(self) -> "FactorCatalog":
        ids = [factor.factor_id for factor in self.factors]
        if len(ids) != len(set(ids)):
            raise ValueError("factor catalog contains duplicate factor IDs")
        return self


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _relative(path: Path, project_root: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _canonical_digest(factors: list[FactorRecord]) -> str:
    payload = [factor.model_dump(mode="json") for factor in sorted(factors, key=lambda x: x.factor_id)]
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _frame_artifact(
    *, path: Path, frame: pd.DataFrame, factor_id: str, project_root: Path, shared: bool
) -> FactorArtifact:
    own = frame.loc[frame["factor_id"].astype(str) == factor_id]
    dates = pd.to_datetime(own["date"], errors="coerce")
    return FactorArtifact(
        path=_relative(path, project_root),
        format="canonical_long_parquet",
        sha256=sha256_file(path),
        rows=len(own),
        instruments=int(own["instrument"].nunique()),
        first_date=dates.min().date() if len(own) else None,
        last_date=dates.max().date() if len(own) else None,
        shared_file=shared,
    )


def _normalize_quanta_result(
    *, source: Path, output: Path, factor_id: str, group: str, version: str
) -> pd.DataFrame:
    value = pd.read_hdf(source, key="data")
    if isinstance(value, pd.DataFrame):
        if value.shape[1] != 1:
            raise ValueError(f"QuantaAlpha result must have one value column: {source}")
        value = value.iloc[:, 0]
    value = value.rename("value")
    frame = value.reset_index()
    frame = frame.rename(columns={"datetime": "date", "symbol": "instrument"})
    if not {"date", "instrument", "value"}.issubset(frame.columns):
        raise ValueError(f"unsupported QuantaAlpha result axes: {source}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    symbols = frame["instrument"].astype(str)
    mapping = {symbol: instrument_from_code(symbol) for symbol in symbols.unique()}
    frame["instrument"] = symbols.map(mapping)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "instrument", "value"])
    frame["available_at"] = frame["date"]
    frame["factor_id"] = factor_id
    frame["factor_group"] = group
    frame["origin"] = "quantaalpha"
    source_digest = sha256_file(source)
    frame["source_id"] = f"quantaalpha-result:{source_digest}"
    frame["version"] = version
    frame = frame[FACTOR_COLUMNS].sort_values(["date", "instrument"])
    frame = frame.drop_duplicates(["date", "instrument", "factor_id"], keep="last")
    _write_parquet_atomic(frame, output)
    return frame


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _diagnostic_summary(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    keys = (
        "observed_at",
        "latest_label_date",
        "observations",
        "coverage",
        "rank_ic_mean",
        "rank_ic_ir",
        "rank_ic_positive_fraction",
        "turnover",
        "max_abs_correlation",
        "warnings",
    )
    return {key: item.get(key) for key in keys if key in item}


def _quanta_metric(backtest: dict[str, Any], *names: str) -> Any:
    """Read QuantaAlpha metrics across its historical key spellings."""

    normalized = {
        re.sub(r"[^a-z0-9]+", "", str(key).lower()): value
        for key, value in backtest.items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", name.lower())
        if key in normalized:
            return normalized[key]
    return None


def _hypothesis_section(text: str, heading: str, next_heading: str | None = None) -> str:
    start = re.search(rf"(?:^|\n)\s*{re.escape(heading)}\s*:\s*", text, re.IGNORECASE)
    if not start:
        return ""
    tail = text[start.end():]
    if next_heading:
        end = re.search(rf"\n\s*{re.escape(next_heading)}\s*:\s*", tail, re.IGNORECASE)
        if end:
            tail = tail[:end.start()]
    return " ".join(tail.split())


def _record_from_registry(
    *,
    item: dict[str, Any],
    diagnostic: dict[str, Any] | None,
    artifact_path: Path,
    artifact_frame: pd.DataFrame,
    project_root: Path,
) -> FactorRecord:
    factor_id = str(item["factor_id"])
    origin = str(item["origin"])
    family = "price_volume" if origin == "aster_deterministic_baseline" else "financial"
    metadata = PRICE_VOLUME_FACTOR_DEFINITIONS.get(factor_id, {})
    coverage = float((diagnostic or {}).get("coverage", 0.0))
    research_eligible = family == "price_volume" and coverage >= 0.75
    return FactorRecord(
        factor_id=factor_id,
        display_name=str(metadata.get("display_name", factor_id)),
        factor_group=str(item["factor_group"]),
        family=family,
        origin=origin,
        version=str(item.get("formula", "unknown")).removeprefix("version="),
        lifecycle_status=LifecycleStatus.VALIDATED,
        status_reason=(
            "Passed real price-volume evidence gates"
            if research_eligible
            else "Canonical PIT values exist but current Council coverage gate is not met"
        ),
        expression=str(metadata.get("expression", item.get("formula", "see source artifact"))),
        description=str(metadata.get("description", item.get("description", factor_id))),
        economic_hypothesis=str(
            metadata.get(
                "economic_hypothesis",
                "Higher disclosed profitability or growth predicts stronger subsequent returns."
                if family == "financial" else "",
            )
        ),
        mechanism_explanation=str(
            metadata.get(
                "mechanism_explanation",
                "Public financial disclosures may be incorporated into prices gradually."
                if family == "financial" else "",
            )
        ),
        expected_direction="positive cross-sectional Rank IC",
        falsification_criteria=[
            "Non-positive matured out-of-sample Rank IC across multiple calendar years",
            "Performance disappears after turnover, redundancy and PIT controls",
        ],
        mechanism_source=(
            "src/aster_portfolio/factors.py:PRICE_VOLUME_FACTOR_DEFINITIONS"
            if family == "price_volume" else "economic prior; requires Council review"
        ),
        implementation_ref=(
            "src/aster_portfolio/factors.py" if family == "price_volume"
            else "src/aster_data/factor_store.py:build_financial_factors"
        ),
        pit_compliant=True,
        research_eligible=research_eligible,
        demo_eligible=True,
        artifact=_frame_artifact(
            path=artifact_path,
            frame=artifact_frame,
            factor_id=factor_id,
            project_root=project_root,
            shared=True,
        ),
        diagnostics=_diagnostic_summary(diagnostic),
        tags=[family, "canonical", "real_data"],
    )


def _text_records(*, project_root: Path, path: Path, manifest_path: Path) -> list[FactorRecord]:
    if not path.exists() or not manifest_path.exists():
        return []
    frame = pd.read_parquet(path)
    manifest = _load_json(manifest_path)
    records = []
    for factor_id in manifest.get("factor_ids", []):
        records.append(
            FactorRecord(
                factor_id=factor_id,
                display_name=factor_id.replace("text_", "").replace("_", " ").title(),
                factor_group="filing_text",
                family="filing_text",
                origin="aster_filing_parser",
                version="aster-filing-text-factors-v1",
                lifecycle_status=LifecycleStatus.CANDIDATE,
                status_reason="Infrastructure smoke only; currently covers two filings",
                expression="See deterministic filing-text implementation",
                description=f"Deterministic filing text feature {factor_id}",
                economic_hypothesis=(
                    "Public filing language contains incremental information about subsequent returns."
                ),
                mechanism_explanation=(
                    "Tone, risk-language density and filing complexity may reveal management outlook or latent operating risk before it is fully incorporated into price."
                ),
                expected_direction="factor-specific; must be established out of sample",
                falsification_criteria=[
                    "No stable matured Rank IC after controlling for document availability",
                    "Signal vanishes after issuer and filing-type controls",
                ],
                mechanism_source="src/aster_data/filing_text_factors.py",
                implementation_ref="src/aster_data/filing_text_factors.py",
                pit_compliant=True,
                research_eligible=False,
                demo_eligible=True,
                artifact=_frame_artifact(
                    path=path,
                    frame=frame,
                    factor_id=factor_id,
                    project_root=project_root,
                    shared=True,
                ),
                diagnostics={"documents": manifest.get("documents", 0)},
                tags=["filing_text", "smoke"],
            )
        )
    return records


def _quanta_records(
    *, project_root: Path, output_root: Path, library_path: Path
) -> list[FactorRecord]:
    if not library_path.exists():
        return []
    library = _load_json(library_path)
    version = f"quantaalpha-library-{library['metadata'].get('version', '1.0')}"
    records = []
    for factor_id, item in sorted(library.get("factors", {}).items()):
        source = Path(item["cache_location"]["result_h5_path"])
        output = output_root / "values" / "quantaalpha" / _safe_name(factor_id) / "v1.parquet"
        frame = _normalize_quanta_result(
            source=source,
            output=output,
            factor_id=factor_id,
            group="quanta_shock_reversal",
            version=version,
        )
        artifact = _frame_artifact(
            path=output,
            frame=frame,
            factor_id=factor_id,
            project_root=project_root,
            shared=False,
        ).model_copy(
            update={
                "source_path": _relative(source, project_root),
                "source_sha256": sha256_file(source),
            }
        )
        backtest = item.get("backtest_results") or {}
        feedback = item.get("feedback") or {}
        metadata = item.get("metadata") or {}
        hypothesis_text = str(metadata.get("hypothesis", ""))
        hypothesis = _hypothesis_section(
            hypothesis_text, "Hypothesis", "Concise Observation"
        )
        justification = _hypothesis_section(
            hypothesis_text, "Concise Justification", "Concise Knowledge"
        )
        knowledge = _hypothesis_section(
            hypothesis_text, "Concise Knowledge", "concise Specification"
        )
        specification = _hypothesis_section(hypothesis_text, "concise Specification")
        records.append(
            FactorRecord(
                factor_id=factor_id,
                display_name=item.get("factor_name", factor_id),
                factor_group="quanta_shock_reversal",
                family="price_volume_ai_mined",
                origin="quantaalpha",
                version=version,
                lifecycle_status=LifecycleStatus.CANDIDATE,
                status_reason="QuantaAlpha candidate; latest AI feedback did not approve promotion",
                expression=item.get("factor_expression", ""),
                description=item.get("factor_description", "QuantaAlpha generated factor"),
                economic_hypothesis=hypothesis,
                mechanism_explanation=" ".join(
                    part for part in (justification, knowledge) if part
                ),
                expected_direction=(
                    "positive cross-sectional Rank IC for the stated forward horizon"
                ),
                falsification_criteria=[
                    specification or "Matured PIT Rank IC is non-positive out of sample",
                    "The effect is unstable across years or redundant with an existing factor",
                ],
                mechanism_source=(
                    _relative(library_path, project_root)
                    + f"#factors.{factor_id}.metadata.hypothesis"
                ),
                implementation_ref=(
                    _relative(library_path, project_root) + f"#factors.{factor_id}"
                ),
                pit_compliant=True,
                research_eligible=False,
                demo_eligible=True,
                artifact=artifact,
                diagnostics={
                    "ic": _quanta_metric(backtest, "ic"),
                    "ic_ir": _quanta_metric(backtest, "icir", "ic_ir"),
                    "rank_ic": _quanta_metric(backtest, "rank ic", "rank_ic"),
                    "rank_ic_ir": _quanta_metric(
                        backtest, "rank icir", "rank_ic_ir"
                    ),
                    "ai_feedback_decision": feedback.get("decision"),
                },
                tags=["price_volume", "ai_mined", "quantaalpha"],
            )
        )
    return records


def _write_catalog(catalog: FactorCatalog, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_root / "catalog.json", catalog.model_dump(mode="json"))
    flat = []
    for factor in catalog.factors:
        row = factor.model_dump(mode="json")
        artifact = row.pop("artifact")
        diagnostics = row.pop("diagnostics")
        row.update({f"artifact_{key}": value for key, value in artifact.items()})
        row["diagnostics_json"] = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)
        row["tags"] = ",".join(row["tags"])
        flat.append(row)
        write_json_atomic(
            output_root / "definitions" / f"{_safe_name(factor.factor_id)}.json",
            factor.model_dump(mode="json"),
        )
    _write_parquet_atomic(pd.DataFrame(flat), output_root / "catalog.parquet")
    manifest = {
        "schema_version": catalog.schema_version,
        "catalog_digest": catalog.catalog_digest,
        "factor_count": len(catalog.factors),
        "counts_by_status": pd.Series(
            [factor.lifecycle_status.value for factor in catalog.factors]
        ).value_counts().sort_index().to_dict(),
        "catalog_json_sha256": sha256_file(output_root / "catalog.json"),
        "catalog_parquet_sha256": sha256_file(output_root / "catalog.parquet"),
    }
    write_json_atomic(output_root / "manifest.json", manifest)


def _merge_previous_record(record: FactorRecord, previous: FactorRecord) -> FactorRecord:
    """Keep governance state without carrying stale QuantaAlpha evidence forward."""

    update: dict[str, Any] = {
        "lifecycle_status": previous.lifecycle_status,
        "status_reason": previous.status_reason,
        "research_eligible": previous.research_eligible,
        "demo_eligible": previous.demo_eligible,
    }
    if record.origin == "quantaalpha":
        if record.artifact.sha256 == previous.artifact.sha256:
            # Preserve canonical Aster diagnostics while refreshing metrics copied
            # from the latest QuantaAlpha library JSON.
            update["diagnostics"] = {**previous.diagnostics, **record.diagnostics}
        else:
            update.update(
                {
                    "lifecycle_status": LifecycleStatus.CANDIDATE,
                    "status_reason": (
                        "QuantaAlpha values changed; canonical diagnostics must be rerun"
                    ),
                    "research_eligible": False,
                }
            )
    return record.model_copy(update=update)


def build_factor_library(
    *, project_root: Path, output_root: Path, quanta_library_path: Path | None = None
) -> FactorCatalog:
    project_root = project_root.resolve()
    output_root = output_root.resolve()
    registry_path = project_root / "data/council/real_evidence_2025/factor_registry.json"
    diagnostics_path = project_root / "data/council/real_evidence_2025/factor_diagnostics.json"
    market_path = project_root / "data/council/real_evidence_2025/market_factors.parquet"
    financial_path = project_root / "data/curated/factors/financial_factors.parquet"
    text_path = project_root / "data/curated/factors/filing_text/filing_text_factors_deterministic.parquet"
    text_manifest = project_root / "data/curated/factors/filing_text/filing_text_manifest_deterministic.json"
    required = (registry_path, diagnostics_path, market_path, financial_path)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"factor library inputs are missing: {missing}")
    if quanta_library_path is None:
        candidates = sorted(
            (project_root / "vendor/quantaalpha-b7ceb27/data/factorlib").glob("*.json"),
            key=lambda path: path.stat().st_mtime,
        )
        quanta_library_path = candidates[-1] if candidates else None

    registry = _load_json(registry_path)
    diagnostics = _load_json(diagnostics_path)
    diagnostics_by_id = {item["factor_id"]: item for item in diagnostics["factors"]}
    market = pd.read_parquet(market_path)
    financial = pd.read_parquet(financial_path)
    records = []
    for item in registry["factors"]:
        path = market_path if item["origin"] == "aster_deterministic_baseline" else financial_path
        frame = market if path == market_path else financial
        records.append(
            _record_from_registry(
                item=item,
                diagnostic=diagnostics_by_id.get(item["factor_id"]),
                artifact_path=path,
                artifact_frame=frame,
                project_root=project_root,
            )
        )
    records.extend(
        _text_records(project_root=project_root, path=text_path, manifest_path=text_manifest)
    )
    if quanta_library_path is not None:
        records.extend(
            _quanta_records(
                project_root=project_root,
                output_root=output_root,
                library_path=quanta_library_path.resolve(),
            )
        )

    previous_path = output_root / "catalog.json"
    if previous_path.exists():
        previous = FactorCatalog.model_validate_json(previous_path.read_text(encoding="utf-8"))
        previous_by_id = {factor.factor_id: factor for factor in previous.factors}
        records = [
            _merge_previous_record(record, previous_by_id[record.factor_id])
            if record.factor_id in previous_by_id else record
            for record in records
        ]
    records = sorted(records, key=lambda factor: factor.factor_id)
    catalog = FactorCatalog(
        generated_at=datetime.now().astimezone(),
        catalog_digest=_canonical_digest(records),
        factors=records,
    )
    _write_catalog(catalog, output_root)
    return catalog


def load_catalog(path: Path) -> FactorCatalog:
    return FactorCatalog.model_validate_json(path.read_text(encoding="utf-8"))


def validate_factor_library(
    *, project_root: Path, catalog_path: Path, deep: bool = True
) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    errors: list[str] = []
    if catalog.catalog_digest != _canonical_digest(catalog.factors):
        errors.append("catalog digest does not match factor records")
    hashes: dict[Path, str] = {}
    frames: dict[Path, pd.DataFrame] = {}
    for factor in catalog.factors:
        path = (project_root / factor.artifact.path).resolve()
        if not path.exists():
            errors.append(f"{factor.factor_id}: artifact is missing: {factor.artifact.path}")
            continue
        hashes.setdefault(path, sha256_file(path))
        if hashes[path] != factor.artifact.sha256:
            errors.append(f"{factor.factor_id}: artifact SHA-256 mismatch")
        if deep and factor.artifact.format == "canonical_long_parquet":
            if path not in frames:
                frames[path] = pd.read_parquet(path)
            frame = frames[path]
            missing = set(FACTOR_COLUMNS).difference(frame.columns)
            if missing:
                errors.append(f"{factor.factor_id}: canonical columns missing: {sorted(missing)}")
                continue
            own = frame.loc[frame["factor_id"].astype(str) == factor.factor_id]
            if len(own) != factor.artifact.rows:
                errors.append(f"{factor.factor_id}: row count differs from catalog")
            if (pd.to_datetime(own["available_at"]) > pd.to_datetime(own["date"])).any():
                errors.append(f"{factor.factor_id}: available_at is after date")
    return {
        "passed": not errors,
        "schema_version": catalog.schema_version,
        "catalog_digest": catalog.catalog_digest,
        "factor_count": len(catalog.factors),
        "artifact_files": len(hashes),
        "errors": errors,
    }


def set_factor_status(
    *,
    output_root: Path,
    factor_id: str,
    new_status: LifecycleStatus,
    reason: str,
    actor: str,
) -> FactorCatalog:
    if not reason.strip() or not actor.strip():
        raise ValueError("reason and actor are required")
    catalog_path = output_root / "catalog.json"
    catalog = load_catalog(catalog_path)
    found = next((factor for factor in catalog.factors if factor.factor_id == factor_id), None)
    if found is None:
        raise KeyError(f"unknown factor_id: {factor_id}")
    old_status = found.lifecycle_status
    if new_status != old_status and new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise ValueError(f"invalid lifecycle transition: {old_status.value} -> {new_status.value}")
    updated = []
    for factor in catalog.factors:
        if factor.factor_id == factor_id:
            factor = factor.model_copy(
                update={"lifecycle_status": new_status, "status_reason": reason}
            )
        updated.append(factor)
    new_catalog = FactorCatalog(
        generated_at=datetime.now().astimezone(),
        catalog_digest=_canonical_digest(updated),
        factors=updated,
    )
    _write_catalog(new_catalog, output_root)
    events_path = output_root / "lifecycle_events.json"
    events = _load_json(events_path).get("events", []) if events_path.exists() else []
    events.append(
        {
            "factor_id": factor_id,
            "from_status": old_status.value,
            "to_status": new_status.value,
            "reason": reason,
            "actor": actor,
            "changed_at": datetime.now().astimezone().isoformat(),
            "catalog_digest": new_catalog.catalog_digest,
        }
    )
    write_json_atomic(events_path, {"events": events})
    return new_catalog


def load_factor_values(
    *, project_root: Path, catalog_path: Path, factor_id: str
) -> pd.DataFrame:
    catalog = load_catalog(catalog_path)
    factor = next((item for item in catalog.factors if item.factor_id == factor_id), None)
    if factor is None:
        raise KeyError(f"unknown factor_id: {factor_id}")
    frame = pd.read_parquet(project_root / factor.artifact.path)
    return frame.loc[frame["factor_id"].astype(str) == factor_id, FACTOR_COLUMNS].copy()


def evaluate_quantaalpha_candidates(
    *,
    project_root: Path,
    catalog_path: Path,
    market_path: Path,
    evidence_root: Path,
    as_of: str,
    horizon: int = 20,
    min_coverage: float = 0.75,
    min_observations: int = 24,
) -> dict[str, Any]:
    """Run canonical Aster diagnostics and promote ready QuantaAlpha candidates.

    QuantaAlpha's own feedback remains provenance only. Research eligibility is
    based on the same deterministic coverage and matured-label readiness gates
    used by the Factor Council; predictive strength is still judged by Council.
    """

    project_root = project_root.resolve()
    catalog_path = catalog_path.resolve()
    catalog = load_catalog(catalog_path)
    candidates = [factor for factor in catalog.factors if factor.origin == "quantaalpha"]
    if not candidates:
        raise ValueError("catalog contains no QuantaAlpha factors")
    factor_paths = sorted(
        {(project_root / factor.artifact.path).resolve() for factor in candidates}
    )
    _, diagnostics = evaluate_factors(
        factor_paths=factor_paths,
        market_path=market_path.resolve(),
        output_root=evidence_root.resolve(),
        as_of=as_of,
        horizon=horizon,
    )
    by_id = {item["factor_id"]: item for item in diagnostics["factors"]}
    updated: list[FactorRecord] = []
    promoted: list[str] = []
    excluded: dict[str, str] = {}
    for factor in catalog.factors:
        if factor.origin != "quantaalpha":
            updated.append(factor)
            continue
        diagnostic = by_id.get(factor.factor_id)
        if diagnostic is None:
            excluded[factor.factor_id] = "canonical evaluator produced no diagnostics"
            updated.append(
                factor.model_copy(
                    update={
                        "research_eligible": False,
                        "status_reason": "Canonical Aster diagnostics are missing",
                    }
                )
            )
            continue
        merged = {
            **factor.diagnostics,
            **_diagnostic_summary(diagnostic),
            "yearly_rank_ic": diagnostic.get("yearly_rank_ic", {}),
            "decay_rank_ic": diagnostic.get("decay_rank_ic", {}),
            "warnings": diagnostic.get("warnings", []),
        }
        ready = (
            int(diagnostic.get("observations", 0)) >= min_observations
            and float(diagnostic.get("coverage", 0.0)) >= min_coverage
        )
        status = factor.lifecycle_status
        if ready and status == LifecycleStatus.CANDIDATE:
            status = LifecycleStatus.VALIDATED
            promoted.append(factor.factor_id)
        if not ready:
            excluded[factor.factor_id] = (
                f"coverage={float(diagnostic.get('coverage', 0.0)):.4f}, "
                f"observations={int(diagnostic.get('observations', 0))}"
            )
        updated.append(
            factor.model_copy(
                update={
                    "lifecycle_status": status,
                    "research_eligible": ready,
                    "status_reason": (
                        "Canonical Aster diagnostics passed research readiness gates; "
                        "predictive merit remains subject to Factor Council review"
                        if ready
                        else "Canonical Aster diagnostics did not pass research readiness gates"
                    ),
                    "diagnostics": merged,
                }
            )
        )
    new_catalog = FactorCatalog(
        generated_at=datetime.now().astimezone(),
        catalog_digest=_canonical_digest(updated),
        factors=sorted(updated, key=lambda factor: factor.factor_id),
    )
    _write_catalog(new_catalog, catalog_path.parent)
    if promoted:
        events_path = catalog_path.parent / "lifecycle_events.json"
        events = _load_json(events_path).get("events", []) if events_path.exists() else []
        changed_at = datetime.now().astimezone().isoformat()
        events.extend(
            {
                "factor_id": factor_id,
                "from_status": LifecycleStatus.CANDIDATE.value,
                "to_status": LifecycleStatus.VALIDATED.value,
                "reason": "Canonical Aster diagnostics passed research readiness gates",
                "actor": "canonical-quanta-evaluator",
                "changed_at": changed_at,
                "catalog_digest": new_catalog.catalog_digest,
            }
            for factor_id in sorted(promoted)
        )
        write_json_atomic(events_path, {"events": events})
    result = {
        "status": "ok",
        "as_of": as_of,
        "horizon": horizon,
        "evaluated": len(candidates),
        "promoted": sorted(promoted),
        "excluded": excluded,
        "catalog_digest": new_catalog.catalog_digest,
        "evidence_root": str(evidence_root.resolve()),
    }
    write_json_atomic(evidence_root / "catalog_update.json", result)
    return result


def export_council_inputs(
    *, catalog_path: Path, output_root: Path, mode: str = "research"
) -> dict[str, Any]:
    if mode not in {"research", "showcase"}:
        raise ValueError("mode must be research or showcase")
    catalog = load_catalog(catalog_path)
    eligible = [
        factor
        for factor in catalog.factors
        if factor.lifecycle_status != LifecycleStatus.RETIRED
        and (factor.research_eligible if mode == "research" else factor.demo_eligible)
    ]
    registry = {
        "version": f"{catalog.schema_version}:{catalog.catalog_digest[:12]}:{mode}",
        "universe": "CSI500_PIT",
        "factors": [
            {
                "factor_id": factor.factor_id,
                "factor_group": factor.factor_group,
                "description": factor.description,
                "economic_hypothesis": factor.economic_hypothesis,
                "mechanism_explanation": factor.mechanism_explanation,
                "expected_direction": factor.expected_direction,
                "falsification_criteria": factor.falsification_criteria,
                "mechanism_source": factor.mechanism_source,
                "origin": factor.origin,
                "formula": factor.expression,
                "approval_status": "approved",
            }
            for factor in eligible
        ],
    }
    required = {
        "observed_at",
        "latest_label_date",
        "observations",
        "coverage",
        "rank_ic_mean",
        "rank_ic_ir",
        "rank_ic_positive_fraction",
        "turnover",
        "max_abs_correlation",
    }
    diagnostic_factors = []
    for factor in eligible:
        if not required.issubset(factor.diagnostics):
            continue
        item = {key: factor.diagnostics[key] for key in required}
        item.update(
            {
                "factor_id": factor.factor_id,
                "yearly_rank_ic": factor.diagnostics.get("yearly_rank_ic", {}),
                "decay_rank_ic": factor.diagnostics.get("decay_rank_ic", {}),
                "warnings": factor.diagnostics.get("warnings", []),
            }
        )
        diagnostic_factors.append(item)
    diagnostics = {"label_horizon_days": 20, "factors": diagnostic_factors}
    output_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_root / "factor_registry.json", registry)
    write_json_atomic(output_root / "factor_diagnostics.json", diagnostics)
    result = {
        "mode": mode,
        "registry_factors": len(registry["factors"]),
        "diagnostic_factors": len(diagnostic_factors),
        "missing_diagnostics": sorted(
            set(item["factor_id"] for item in registry["factors"])
            - set(item["factor_id"] for item in diagnostic_factors)
        ),
        "registry_path": str((output_root / "factor_registry.json").resolve()),
        "diagnostics_path": str((output_root / "factor_diagnostics.json").resolve()),
    }
    write_json_atomic(output_root / "export_manifest.json", result)
    return result
