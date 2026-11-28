"""Point-in-time refresh of the Factor Council evidence chain.

The console replay used to reuse whatever Council packet happened to exist and
label it "current" for every later quarter.  Because the newest packet was dated
2025-12-31, all four 2026 quarters silently ran on stale diagnostics and the
chair fell back to the two-factor default pair.

This module rebuilds the chain for one quarter-cutoff:

1. rebuild the deterministic price-volume factor file from the market store;
2. rebase the catalogue's conventional records onto that fresh file;
3. re-evaluate every research-eligible factor as of the cutoff (PIT labels);
4. export the research Council inputs (registry + diagnostics);
5. build the Factor Council packet for that cutoff.

Council deliberation itself stays a separate step because it calls the LLM.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from aster_data.factor_evidence import build_market_context, build_market_factors
from aster_data.factor_library import (
    evaluate_quantaalpha_candidates,
    export_council_inputs,
    load_catalog,
    rebase_market_factor_artifacts,
)

from .evidence import DecisionPacketBuilder, write_packet
from .schemas import CouncilMode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKET = PROJECT_ROOT / "data" / "curated" / "market" / "daily.parquet"
DEFAULT_POLICY = PROJECT_ROOT / "config" / "council" / "real_policy.json"
DEFAULT_LIBRARY = PROJECT_ROOT / "data" / "curated" / "factor_library"


def _evaluation_chunks(catalog) -> list[tuple[str, tuple[str, ...], set[str] | None]]:
    """Split re-evaluation into bounded chunks so the full library never has to
    be concatenated into a single frame (26 QuantaAlpha factors alone hold
    roughly 70M rows).  Conventional and style origins are small enough to run
    whole; QuantaAlpha is evaluated group by group."""

    groups_by_origin: dict[str, set[str]] = defaultdict(set)
    for factor in catalog.factors:
        groups_by_origin[factor.origin].add(factor.factor_group)
    plan: list[tuple[str, tuple[str, ...], set[str] | None]] = []
    if "aster_deterministic_baseline" in groups_by_origin:
        plan.append(("conventional", ("aster_deterministic_baseline",), None))
    if "aster_style_factors" in groups_by_origin:
        plan.append(("style", ("aster_style_factors",), None))
    for group in sorted(groups_by_origin.get("quantaalpha", set())):
        plan.append((f"quanta-{group}", ("quantaalpha",), {group}))
    return plan


def refresh_quarter_evidence(
    *,
    cutoff: str,
    output_root: Path,
    project_root: Path = PROJECT_ROOT,
    market_path: Path = DEFAULT_MARKET,
    policy_path: Path = DEFAULT_POLICY,
    library_root: Path = DEFAULT_LIBRARY,
    mode: str = CouncilMode.RESEARCH.value,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    market_path = market_path.resolve()
    output_root = (output_root / cutoff).resolve()
    library_dir = output_root / "library"
    evidence_dir = output_root / "evidence"
    inputs_dir = output_root / "council_inputs"
    packet_path = output_root / "packet.json"
    library_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    source_catalog = (library_root / "catalog.json").resolve()
    if not source_catalog.exists():
        raise FileNotFoundError(f"factor library catalogue is missing: {source_catalog}")
    working_catalog = library_dir / "catalog.json"
    shutil.copy2(source_catalog, working_catalog)

    market_factor_path = evidence_dir / "market_factors.parquet"
    market_factors = build_market_factors(
        market_path=market_path, output_path=market_factor_path, as_of=cutoff
    )
    rebase_market_factor_artifacts(
        catalog_path=working_catalog, market_path=market_factor_path, project_root=project_root
    )

    catalog = load_catalog(working_catalog)
    chunks = []
    for name, origins, groups in _evaluation_chunks(catalog):
        result = evaluate_quantaalpha_candidates(
            project_root=project_root,
            catalog_path=working_catalog,
            market_path=market_path,
            evidence_root=evidence_dir / "eval" / name,
            as_of=cutoff,
            origins=origins,
            groups=groups,
        )
        chunks.append({"chunk": name, "evaluated": result["evaluated"]})
        catalog = load_catalog(working_catalog)

    export = export_council_inputs(
        catalog_path=working_catalog, output_root=inputs_dir, mode=mode
    )
    market_state_path = evidence_dir / "market_state.json"
    build_market_context(
        market_path=market_path, as_of=cutoff, output_path=market_state_path
    )
    packet = DecisionPacketBuilder().build_from_files(
        registry_path=inputs_dir / "factor_registry.json",
        diagnostics_path=inputs_dir / "factor_diagnostics.json",
        market_path=market_state_path,
        policy_path=policy_path.resolve(),
        decision_at=date.fromisoformat(cutoff),
        input_cutoff=date.fromisoformat(cutoff),
        mode=CouncilMode(mode),
    )
    write_packet(packet, packet_path)

    diagnostics = json.loads((inputs_dir / "factor_diagnostics.json").read_text(encoding="utf-8"))
    observed = sorted({item["observed_at"] for item in diagnostics["factors"]})
    summary = {
        "cutoff": cutoff,
        "packet_path": str(packet_path),
        "packet_digest": packet.packet_digest,
        "market_factor_rows": market_factors["rows"],
        "chunks": chunks,
        "registry_factors": export["registry_factors"],
        "diagnostic_factors": export["diagnostic_factors"],
        "missing_diagnostics": export["missing_diagnostics"],
        "diagnostic_observed_at": observed,
        "groups": [group.group_id for group in packet.factor_groups],
        "excluded": packet.excluded_factors,
        "catalog_digest": catalog.catalog_digest,
    }
    (output_root / "refresh.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def run_council(
    *,
    packet_path: Path,
    output_root: Path,
    scripts_root: Path | None = None,
) -> dict[str, Any]:
    """Run the LLM Factor Council for a refreshed packet (uses the stored key)."""

    scripts_root = (scripts_root or (PROJECT_ROOT / "scripts")).resolve()
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(scripts_root / "run_factor_council.ps1"),
        "-PacketPath",
        str(packet_path.resolve()),
        "-OutputRoot",
        str(output_root.resolve()),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(
            "factor council failed: "
            + (completed.stderr or completed.stdout or "")[-2000:]
        )
    return {
        "packet": str(packet_path),
        "stdout_tail": (completed.stdout or "")[-800:],
    }
