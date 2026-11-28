"""Export a small, sanitised snapshot for the Aster Research Console."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime

import pandas as pd
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BENCHMARK_CLOSES: pd.Series | None = None


def benchmark_closes() -> pd.Series:
    """CSI 500 close series, cached for the lifetime of one exporter process."""
    global _BENCHMARK_CLOSES
    if _BENCHMARK_CLOSES is None:
        market = pd.read_parquet(
            PROJECT_ROOT / "data/curated/market/daily.parquet",
            columns=["date", "instrument", "close"],
        )
        series = (
            market.loc[market["instrument"] == "SH000905", ["date", "close"]]
            .drop_duplicates("date", keep="last")
            .set_index("date")["close"]
            .sort_index()
        )
        series.index = pd.to_datetime(series.index)
        _BENCHMARK_CLOSES = series
    return _BENCHMARK_CLOSES


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
        "completed_artifacts", "total_artifacts", "instrument_index", "instruments",
        "stage", "stage_index", "stage_completed", "stages", "jobs_total", "job_index",
        "current_id", "run_id",
    }
    result = {key: value for key, value in status.items() if key in allowed}
    if isinstance(status.get("token_usage"), dict):
        result["token_usage"] = {
            key: status["token_usage"].get(key, 0)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
    if result.get("state") == "complete" and result.get("documents_scored") is not None:
        result.setdefault("score_completed", result["documents_scored"])
        result.setdefault("score_total", result.get("documents_total", result["documents_scored"]))
        result.setdefault(
            "parse_completed",
            max(0, int(result.get("documents_total", 0)) - int(result.get("failures", 0))),
        )
        result.setdefault("parse_failures", result.get("failures", 0))
        result.setdefault("score_failures", result.get("failures", 0))
    return {"name": name, **result}


def filing_snapshot(years: range = range(2020, 2026)) -> dict[str, Any]:
    """Return a six-year filing summary without exposing document or host paths."""
    annual = []
    for year in years:
        item = public_job(
            f"{year} annual filing intelligence",
            PROJECT_ROOT / f"run/filing_factor_{year}/status.json",
        )
        item["year"] = year
        annual.append(item)

    def total(key: str) -> int:
        return sum(int(item.get(key) or 0) for item in annual)

    states = {str(item.get("state") or "pending") for item in annual}
    if states == {"complete"}:
        state = "complete"
    elif "running" in states:
        state = "running"
    elif states == {"pending"}:
        state = "pending"
    else:
        state = "attention"
    updated = max((str(item.get("updated_at") or "") for item in annual), default="")
    usage = {
        key: sum(int((item.get("token_usage") or {}).get(key) or 0) for item in annual)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return {
        "name": "2020-2025 annual filing intelligence",
        "state": state,
        "year_start": annual[0]["year"] if annual else None,
        "year_end": annual[-1]["year"] if annual else None,
        "years": annual,
        "documents_total": total("documents_total"),
        "parse_completed": total("parse_completed"),
        "parse_failures": total("parse_failures"),
        "score_completed": total("score_completed"),
        "score_total": total("score_total"),
        "score_failures": total("score_failures"),
        "factor_rows": total("factor_rows"),
        "needs_ocr": total("needs_ocr"),
        "token_usage": usage,
        "updated_at": updated or None,
    }


def quanta_factor_rows(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose newly mined price-volume factors as candidates before promotion."""
    root = PROJECT_ROOT / "vendor/quantaalpha-b7ceb27/data/factorlib"
    paths = sorted(
        [
            *root.glob("all_factors_library_aster_pv_*.json"),
            *root.glob("all_factors_library_aster_fd_*.json"),
        ],
        key=lambda path: path.stat().st_mtime,
    )
    paths = [path for path in paths if "smoke" not in path.name]
    known_ids = {str(item.get("id")) for item in existing}
    known_names = {str(item.get("name")) for item in existing}
    discovered: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = load_json(path, {}) or {}
        match = re.search(r"aster_pv_([ab]\d{2})", path.name, re.IGNORECASE)
        directory_match = re.search(r"aster_fd_(fd\d{2})", path.name, re.IGNORECASE)
        group = (
            f"PV-{match.group(1).upper()}"
            if match
            else f"FD-{directory_match.group(1).upper()}"
            if directory_match
            else "price_volume"
        )
        for raw in (payload.get("factors") or {}).values():
            factor_id = str(raw.get("factor_id") or "")
            name = str(raw.get("factor_name") or factor_id)
            if not factor_id or factor_id in known_ids or name in known_names:
                continue
            metrics = raw.get("backtest_results") or {}
            metadata = raw.get("metadata") or {}
            hypothesis = str(metadata.get("initial_direction") or metadata.get("hypothesis") or "")
            digest = hashlib.sha256(
                f"{factor_id}|{raw.get('factor_expression', '')}".encode("utf-8")
            ).hexdigest()[:12]
            discovered[name] = {
                "id": factor_id,
                "name": name,
                "group": group,
                "family": "price_volume",
                "origin": "quantaalpha",
                "status": "candidate",
                "researchEligible": False,
                "demoEligible": False,
                "pitCompliant": True,
                "expression": raw.get("factor_expression", ""),
                "description": raw.get("factor_description", ""),
                "hypothesis": hypothesis,
                "mechanism": raw.get("factor_description", ""),
                "expectedDirection": "Empirical sign remains subject to canonical evaluation.",
                "falsificationCriteria": [
                    "Reject if the signal depends on isolated volume spikes.",
                    "Reject if the sign is unstable across evaluation periods.",
                ],
                "mechanismSource": "quantaalpha_hypothesis",
                "tags": ["ai-mined", "price-volume", group.lower()],
                "version": "mined-candidate-v1",
                "statusReason": "Awaiting canonical evaluation and factor-library promotion.",
                "metrics": {
                    "rankIc": metrics.get("Rank IC"),
                    "rankIcIr": metrics.get("Rank ICIR"),
                    "coverage": None,
                    "turnover": None,
                    "correlation": None,
                    "observations": None,
                },
                "yearlyRankIc": {},
                "artifact": {
                    "rows": 0,
                    "instruments": 0,
                    "firstDate": None,
                    "lastDate": None,
                    "digest": digest,
                },
            }
    return list(discovered.values())


def factor_mining_snapshot() -> dict[str, Any]:
    root = PROJECT_ROOT / "vendor/quantaalpha-b7ceb27/data/factorlib"
    paths = [
        path
        for pattern in ("all_factors_library_aster_pv_*.json", "all_factors_library_aster_fd_*.json")
        for path in root.glob(pattern)
        if "smoke" not in path.name
    ]
    directions: set[str] = set()
    factors = 0
    for path in paths:
        match = re.search(r"aster_pv_([ab]\d{2})", path.name, re.IGNORECASE)
        if match:
            directions.add(match.group(1).upper())
        directory_match = re.search(r"aster_fd_(fd\d{2})", path.name, re.IGNORECASE)
        if directory_match:
            directions.add(directory_match.group(1).upper())
        payload = load_json(path, {}) or {}
        factors += len(payload.get("factors") or {})
    return {
        "name": "QuantaAlpha price-volume mining",
        "state": "complete" if len(directions) >= 16 else "running" if directions else "pending",
        "completed": len(directions),
        "total": 16,
        "factor_count": factors,
        "factor_ids": sorted(directions),
        "updated_at": (
            datetime.fromtimestamp(max(path.stat().st_mtime for path in paths)).astimezone().isoformat()
            if paths else None
        ),
    }


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
    translations = load_json(PROJECT_ROOT / "data/console/factor_translations.json", {}) or {}
    for row in rows:
        translated = translations.get(str(row.get("id")))
        if translated:
            row["descriptionZh"] = translated.get("description_zh")
            row["hypothesisZh"] = translated.get("hypothesis_zh")
            row["mechanismZh"] = translated.get("mechanism_zh")
            row["expectedDirectionZh"] = translated.get("expected_direction_zh")
            row["falsificationCriteriaZh"] = translated.get("falsification_criteria_zh")
    return rows


def council_snapshot() -> dict[str, Any]:
    roots = [
        PROJECT_ROOT / "data/council/real_runs",
        PROJECT_ROOT / "data/council/showcase_runs",
        PROJECT_ROOT / "data/council/filing_ai_showcase_runs",
    ]
    candidates = [
        path
        for root in roots if root.exists()
        for path in root.glob("*")
        if path.is_dir() and (path / "decision.json").exists()
    ]
    run_dir = max(
        candidates,
        key=lambda path: (path / "decision.json").stat().st_mtime,
        default=None,
    )
    fallback_packet = PROJECT_ROOT / "run/factor_library_validation/research_packet_v2.json"
    packet_path = run_dir / "packet.json" if run_dir and (run_dir / "packet.json").exists() else fallback_packet
    packet = load_json(packet_path, {}) or {}
    decision = load_json(run_dir / "decision.json", {}) if run_dir else {}
    ballots = []
    if run_dir and (run_dir / "ballots").exists():
        for path in sorted((run_dir / "ballots").glob("*.json")):
            ballot = load_json(path, {}) or {}
            ballots.append({
                "role": ballot.get("role", path.stem),
                "summary": ballot.get("summary", ""),
                "summaryZh": ballot.get("summary_zh"),
                "votes": ballot.get("votes", []),
                "dissentConditionsZh": ballot.get("dissent_conditions_zh", []),
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
                    "hypothesisZh": factor.get("economic_hypothesis_zh"),
                    "mechanism": factor.get("mechanism_explanation", ""),
                    "mechanismZh": factor.get("mechanism_explanation_zh"),
                    "expectedDirection": factor.get("expected_direction", ""),
                    "expectedDirectionZh": factor.get("expected_direction_zh"),
                    "falsificationCriteria": factor.get("falsification_criteria", []),
                    "falsificationCriteriaZh": factor.get("falsification_criteria_zh", []),
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
            "rationaleZh": decision.get("rationale_zh"),
            "confidence": decision.get("confidence"),
            "fallbackUsed": bool(decision.get("fallback_used")),
            "fallbackReason": decision.get("fallback_reason"),
            "promptVersion": decision.get("prompt_version"),
            "dissent": decision.get("dissent", []),
            "isHistorical": True,
            "mode": decision.get("mode", "research"),
            "usesHindsight": bool(decision.get("uses_hindsight", False)),
            "disclosure": decision.get("disclosure"),
        },
        "ballots": ballots,
        "mechanismReviewPending": not any(item.get("mechanismReviews") for item in ballots),
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def curve_from_rows(rows: list[dict[str, Any]], limit: int = 180) -> list[dict[str, Any]]:
    if not rows:
        return []
    step = max(1, len(rows) // limit)
    selected = rows[::step]
    if selected[-1] is not rows[-1]:
        selected.append(rows[-1])
    benchmark_nav: dict[str, float] = {}
    try:
        closes = benchmark_closes()
        base_date = pd.Timestamp(rows[0]["date"])
        base_close = float(closes.loc[:base_date].iloc[-1])
        base_nav = float(rows[0].get("nav") or 1.0)
        for row in selected:
            day = pd.Timestamp(row["date"])
            benchmark_nav[row["date"]] = base_nav * float(closes.loc[:day].iloc[-1]) / base_close
    except Exception:
        benchmark_nav = {}
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
            "benchmarkNav": round(benchmark_nav[row["date"]], 4) if row["date"] in benchmark_nav else None,
        })
    return result


def curve(path: Path, limit: int = 180) -> list[dict[str, Any]]:
    return curve_from_rows(read_rows(path), limit)


DEMO_RUNS: list[tuple[str, str, str]] = [
    (
        "narrative_monthly_v3",
        "MONTHLY DEMO · beta 0.2 · tech-crash shorts",
        "data/portfolio/narrative_demo/narrative_monthly_v3",
    ),
    (
        "narrative_v2",
        "QUARTERLY DEMO · beta 0.4",
        "data/portfolio/narrative_demo/narrative_v2",
    ),
    (
        "demo_showcase_v1",
        "SHOWCASE DEMO · beta +/-0.5",
        "data/portfolio/demo_showcase/demo_showcase_v1",
    ),
]


def demo_runs() -> list[dict[str, Any]]:
    """Disclosed demo curves, normalised to the displayed window."""
    runs = []
    for run_id, label, relative in DEMO_RUNS:
        root = PROJECT_ROOT / relative
        summary = load_json(root / "summary.json", {}) or {}
        rows = read_rows(root / "run" / "daily.csv")
        if not rows or not summary:
            continue
        window_start = summary.get("window_start") or rows[0]["date"]
        rows = [row for row in rows if row["date"] >= window_start]
        if not rows:
            continue
        base_nav = float(rows[0]["nav"])
        rows = [{**row, "nav": str(float(row["nav"]) / base_nav)} for row in rows]
        betas = [abs(float(row.get("estimated_net_beta") or 0.0)) for row in rows]
        gross = [float(row.get("gross_exposure") or 0.0) for row in rows]
        costs = [float(row.get("cost_fraction") or 0.0) for row in rows]
        stock_turn = [float(row.get("stock_turnover") or 0.0) for row in rows]
        futures_turn = [float(row.get("futures_turnover") or 0.0) for row in rows]
        report_paths = sorted((root / "reports").glob("*.json")) if (root / "reports").exists() else []
        report = load_json(report_paths[-1], {}) if report_paths else {}
        positioning = report.get("positioning") or {}
        runs.append({
            "id": run_id,
            "label": label,
            "source": "demo",
            "disclosure": summary.get("disclosure"),
            "report": {
                "decisionAt": report.get("decision_at"),
                "effectiveTo": report.get("effective_to"),
                "profile": positioning.get("profile"),
                "targetBeta": positioning.get("target_beta"),
                "memo": report.get("memo"),
                "memoEn": report.get("memo_en"),
                "confidence": report.get("confidence"),
            } if report else None,
            "metrics": {
                "annual_return": summary.get("annual_return"),
                "annual_volatility": summary.get("annual_volatility"),
                "sharpe": summary.get("sharpe"),
                "max_drawdown": summary.get("max_drawdown"),
                "max_abs_estimated_beta": max(betas) if betas else None,
                "mean_gross_exposure": sum(gross) / len(gross) if gross else None,
                "total_cost_fraction": sum(costs),
                "total_stock_turnover": sum(stock_turn),
                "total_futures_turnover": sum(futures_turn),
            },
            "curve": curve_from_rows(rows),
            "council": {
                "selectedProfile": None,
                "overweights": [],
                "underweights": [],
                "activeTilt": 0.0,
            },
        })
    return runs


def portfolio_snapshot() -> dict[str, Any]:
    root = PROJECT_ROOT / "data/portfolio/real_runs"
    candidates = sorted(
        [path for path in root.glob("*") if (path / "metrics.json").exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    runs = demo_runs()
    for path in candidates[:3]:
        manifest = load_json(path / "manifest.json", {}) or {}
        council = manifest.get("portfolio_council") or {}
        runs.append({
            "id": path.name,
            "label": path.name.replace("_", " "),
            "metrics": load_json(path / "metrics.json", {}) or {},
            "curve": curve(path / "daily.csv"),
            "council": {
                "selectedProfile": manifest.get("selected_profile_id"),
                "overweights": council.get("industry_overweights", []),
                "underweights": council.get("industry_underweights", []),
                "activeTilt": council.get("industry_active_tilt", 0.0),
                "effectiveStart": council.get("effective_start"),
                "effectiveEnd": council.get("effective_end"),
                "usesHindsight": bool(council.get("uses_hindsight", False)),
                "industryOverrideSignals": manifest.get("industry_override_signals", 0),
            },
        })
    return {"runs": runs}


def build_snapshot() -> dict[str, Any]:
    catalog = load_json(PROJECT_ROOT / "data/curated/factor_library/catalog.json", {}) or {}
    factors = factor_rows(catalog)
    factors.extend(quanta_factor_rows(factors))
    filing = filing_snapshot()
    mining = factor_mining_snapshot()
    market = public_job("CSI500 market", PROJECT_ROOT / "run/akshare_market/status.json")
    factor_inputs = public_job("factor inputs", PROJECT_ROOT / "run/factor_input_download/status.json")
    financial = public_job("financial statements", PROJECT_ROOT / "run/parallel_financial/status.json")
    jobs = [
        filing,
        mining,
        market,
        factor_inputs,
        financial,
    ]
    council = council_snapshot()
    validated = sum(item["status"] in {"validated", "council_approved", "demo_selected"} for item in factors)
    quanta = sum(item["origin"] == "quantaalpha" for item in factors)
    scored = int(filing.get("score_completed") or 0)
    score_total = int(filing.get("score_total") or filing.get("documents_total") or 0)
    data_running = any(item.get("state") == "running" for item in (market, factor_inputs, financial))
    data_detail = "CSI500 PIT + OHLCV"
    if factor_inputs.get("total_artifacts"):
        data_detail = f"{factor_inputs.get('completed_artifacts', 0)}/{factor_inputs['total_artifacts']} factor inputs"
    if scored >= score_total:
        filing_state = "complete"
    elif filing.get("state") == "complete":
        filing_state = "attention"
    else:
        filing_state = "running"
    pipeline = [
        {"id": "data", "label": "Data spine", "detail": data_detail, "state": "running" if data_running else "complete", "view": "overview"},
        {"id": "filings", "label": "Filing intelligence", "detail": f"{scored}/{score_total} scored (2020-25)", "state": filing_state, "view": "filings"},
        {"id": "mining", "label": "AI factor mining", "detail": f"{mining['completed']}/{mining['total']} directions · {quanta} candidates", "state": mining["state"], "view": "factors"},
        {"id": "evaluation", "label": "Canonical evaluation", "detail": f"{validated}/{len(factors)} validated", "state": "complete" if validated == len(factors) else "attention", "view": "factors"},
        {"id": "council", "label": "Factor Council", "detail": f"{len(council['decision']['selectedGroups'])} groups selected", "state": "attention" if council["decision"]["fallbackUsed"] else "complete", "view": "council"},
        {"id": "portfolio", "label": "Portfolio replay", "detail": "Optimisation + IC hedge", "state": "complete", "view": "portfolio"},
    ]
    return {
        "meta": {
            "schema": "aster-console-snapshot-v2",
            "generatedAt": datetime.now().astimezone().isoformat(),
            "asOf": council["packet"].get("decisionAt") or datetime.now().date().isoformat(),
            "catalogDigest": str(catalog.get("catalog_digest", ""))[:12],
            "mode": council["decision"].get("mode", "research"),
            "showcaseDisclosure": council["decision"].get("disclosure") or "Retrospective course-demo reenactment uses hindsight-selected scenarios and is not a live prediction.",
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
