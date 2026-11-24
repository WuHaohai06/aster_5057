"""Export a small, sanitised snapshot for the Aster Research Console."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def latest_directory(root: Path) -> Path | None:
    directories = [path for path in root.glob("*") if path.is_dir()]
    return max(directories, key=lambda path: path.stat().st_mtime) if directories else None


def public_job(name: str, path: Path) -> dict[str, Any]:
    status = load_json(path, {}) or {}
    allowed = {
        "state", "updated_at", "documents_total", "parse_completed", "parse_failures",
        "score_completed", "score_total", "score_failures", "factor_rows", "needs_ocr",
        "documents_scored", "completed_at", "failures", "factor_ids",
        "completed", "total", "failed", "succeeded", "current", "phase",
    }
    result = {key: value for key, value in status.items() if key in allowed}
    if isinstance(status.get("token_usage"), dict):
        result["token_usage"] = {
            key: status["token_usage"].get(key, 0)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
    if result.get("state") == "complete" and result.get("documents_scored") is not None:
        result.setdefault("score_completed", result["documents_scored"])
        result.setdefault("score_total", result["documents_scored"])
        result.setdefault("parse_completed", result.get("documents_total", 0))
        result.setdefault("parse_failures", result.get("failures", 0))
        result.setdefault("score_failures", 0)
    return {"name": name, **result}


def factor_rows(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for factor in catalog.get("factors", []):
        diagnostics = factor.get("diagnostics") or {}
        artifact = factor.get("artifact") or {}
        rows.append({
            "id": factor.get("factor_id"),
            "name": factor.get("display_name"),
            "group": factor.get("factor_group"),
            "family": factor.get("family"),
            "origin": factor.get("origin"),
            "status": factor.get("lifecycle_status"),
            "researchEligible": bool(factor.get("research_eligible")),
            "demoEligible": bool(factor.get("demo_eligible")),
            "pitCompliant": bool(factor.get("pit_compliant")),
            "expression": factor.get("expression", ""),
            "description": factor.get("description", ""),
            "hypothesis": factor.get("economic_hypothesis", ""),
            "mechanism": factor.get("mechanism_explanation", ""),
            "expectedDirection": factor.get("expected_direction", ""),
            "falsificationCriteria": factor.get("falsification_criteria", []),
            "mechanismSource": factor.get("mechanism_source", ""),
            "tags": factor.get("tags", []),
            "version": factor.get("version", ""),
            "statusReason": factor.get("status_reason", ""),
            "metrics": {
                "rankIc": diagnostics.get("rank_ic_mean", diagnostics.get("rank_ic")),
                "rankIcIr": diagnostics.get("rank_ic_ir"),
                "coverage": diagnostics.get("coverage"),
                "turnover": diagnostics.get("turnover"),
                "correlation": diagnostics.get("max_abs_correlation"),
                "observations": diagnostics.get("observations"),
            },
            "yearlyRankIc": diagnostics.get("yearly_rank_ic", {}),
            "artifact": {
                "rows": artifact.get("rows", 0),
                "instruments": artifact.get("instruments", 0),
                "firstDate": artifact.get("first_date"),
                "lastDate": artifact.get("last_date"),
                "digest": str(artifact.get("sha256", ""))[:12],
            },
        })
    return rows


def council_snapshot() -> dict[str, Any]:
    packet_path = PROJECT_ROOT / "run/factor_library_validation/research_packet_v2.json"
    packet = load_json(packet_path, {}) or {}
    runs_root = PROJECT_ROOT / "data/council/real_runs"
    run_dir = latest_directory(runs_root)
    decision = load_json(run_dir / "decision.json", {}) if run_dir else {}
    ballots = []
    if run_dir and (run_dir / "ballots").exists():
        for path in sorted((run_dir / "ballots").glob("*.json")):
            ballot = load_json(path, {}) or {}
            ballots.append({
                "role": ballot.get("role", path.stem),
                "summary": ballot.get("summary", ""),
                "votes": ballot.get("votes", []),
                "mechanismReviews": ballot.get("mechanism_reviews", []),
                "dissentConditions": ballot.get("dissent_conditions", []),
            })
    groups = []
    for group in packet.get("factor_groups", []):
        groups.append({
            "id": group.get("group_id"),
            "factorIds": [factor.get("factor_id") for factor in group.get("factors", [])],
            "rankIc": group.get("rank_ic_mean_median"),
            "rankIcIr": group.get("rank_ic_ir_median"),
            "turnover": group.get("turnover_median"),
            "correlation": group.get("max_abs_correlation"),
            "mechanisms": [
                {
                    "factorId": factor.get("factor_id"),
                    "hypothesis": factor.get("economic_hypothesis", ""),
                    "mechanism": factor.get("mechanism_explanation", ""),
                    "expectedDirection": factor.get("expected_direction", ""),
                    "falsificationCriteria": factor.get("falsification_criteria", []),
                }
                for factor in group.get("factors", [])
            ],
        })
    return {
        "packet": {
            "version": packet.get("packet_version"),
            "decisionAt": packet.get("decision_at"),
            "inputCutoff": packet.get("input_cutoff"),
            "digest": str(packet.get("packet_digest", ""))[:12],
            "groups": groups,
        },
        "decision": {
            "decisionAt": decision.get("decision_at"),
            "status": decision.get("status", "not_run"),
            "selectedGroups": decision.get("selected_groups", []),
            "disabledGroups": decision.get("disabled_groups", []),
            "rationale": decision.get("rationale", ""),
            "confidence": decision.get("confidence"),
            "fallbackUsed": bool(decision.get("fallback_used")),
            "fallbackReason": decision.get("fallback_reason"),
            "promptVersion": decision.get("prompt_version"),
            "dissent": decision.get("dissent", []),
            "isHistorical": True,
        },
        "ballots": ballots,
        "mechanismReviewPending": not any(item.get("mechanismReviews") for item in ballots),
    }


def curve(path: Path, limit: int = 180) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return []
    step = max(1, len(rows) // limit)
    selected = rows[::step]
    if selected[-1] is not rows[-1]:
        selected.append(rows[-1])
    peak = 0.0
    result = []
    for row in selected:
        nav = float(row.get("nav") or 0.0)
        peak = max(peak, nav)
        result.append({
            "date": row.get("date"),
            "nav": nav,
            "drawdown": nav / peak - 1.0 if peak else 0.0,
            "beta": float(row.get("estimated_net_beta") or 0.0),
            "profile": row.get("profile_id") or "unassigned",
        })
    return result


def portfolio_snapshot() -> dict[str, Any]:
    root = PROJECT_ROOT / "data/portfolio/real_runs"
    candidates = sorted(
        [path for path in root.glob("*") if (path / "metrics.json").exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    runs = []
    for path in candidates[:3]:
        runs.append({
            "id": path.name,
            "label": path.name.replace("_", " "),
            "metrics": load_json(path / "metrics.json", {}) or {},
            "curve": curve(path / "daily.csv"),
        })
    return {"runs": runs}


def build_snapshot() -> dict[str, Any]:
    catalog = load_json(PROJECT_ROOT / "data/curated/factor_library/catalog.json", {}) or {}
    factors = factor_rows(catalog)
    filing = public_job(
        "2025 annual filing intelligence",
        PROJECT_ROOT / "run/filing_factor_2025/status.json",
    )
    jobs = [
        filing,
        public_job("CSI500 market", PROJECT_ROOT / "run/akshare_market/status.json"),
        public_job("factor inputs", PROJECT_ROOT / "run/factor_input_download/status.json"),
        public_job("financial statements", PROJECT_ROOT / "run/parallel_financial/status.json"),
    ]
    council = council_snapshot()
    validated = sum(item["status"] in {"validated", "council_approved", "demo_selected"} for item in factors)
    quanta = sum(item["origin"] == "quantaalpha" for item in factors)
    scored = int(filing.get("score_completed") or 0)
    score_total = int(filing.get("score_total") or filing.get("documents_total") or 0)
    pipeline = [
        {"id": "data", "label": "Data spine", "detail": "CSI500 PIT + OHLCV", "state": "complete", "view": "overview"},
        {"id": "filings", "label": "Filing intelligence", "detail": f"{scored}/{score_total} scored", "state": "running" if scored < score_total else "complete", "view": "filings"},
        {"id": "mining", "label": "AI factor mining", "detail": f"{quanta} Quanta candidates", "state": "complete" if quanta else "pending", "view": "factors"},
        {"id": "evaluation", "label": "Canonical evaluation", "detail": f"{validated}/{len(factors)} validated", "state": "complete", "view": "factors"},
        {"id": "council", "label": "Factor Council", "detail": f"{len(council['decision']['selectedGroups'])} groups selected", "state": "attention" if council["decision"]["fallbackUsed"] else "complete", "view": "council"},
        {"id": "portfolio", "label": "Portfolio replay", "detail": "Optimisation + IC hedge", "state": "complete", "view": "portfolio"},
    ]
    return {
        "meta": {
            "schema": "aster-console-snapshot-v1",
            "generatedAt": datetime.now().astimezone().isoformat(),
            "asOf": council["packet"].get("decisionAt") or datetime.now().date().isoformat(),
            "catalogDigest": str(catalog.get("catalog_digest", ""))[:12],
            "mode": "research",
            "showcaseDisclosure": "Retrospective course-demo reenactment uses hindsight-selected scenarios and is not a live prediction.",
        },
        "pipeline": pipeline,
        "jobs": jobs,
        "factors": factors,
        "factorCouncil": council,
        "portfolio": portfolio_snapshot(),
        "filings": filing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "apps/aster-console/public/data/snapshot.json",
    )
    args = parser.parse_args()
    payload = build_snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(args.output.resolve()),
        "factors": len(payload["factors"]),
        "pipeline_stages": len(payload["pipeline"]),
        "portfolio_runs": len(payload["portfolio"]["runs"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
