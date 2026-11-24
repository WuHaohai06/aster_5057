"""Research audit, experiment design, attribution and release helpers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from aster_data.io import sha256_file, write_bytes_atomic, write_json_atomic


def verify_research_inputs(
    *, market_path: Path, factor_paths: list[Path], futures_path: Path | None = None
) -> dict:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    market = pd.read_parquet(market_path)
    required_market = {"date", "instrument", "open", "high", "low", "close", "volume", "csi500_member"}
    add("market_schema", not required_market.difference(market.columns), str(sorted(required_market.difference(market.columns))))
    if not required_market.difference(market.columns):
        duplicate = market.duplicated(["date", "instrument"]).sum()
        add("market_unique_key", duplicate == 0, f"duplicates={duplicate}")
        invalid = ((market[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum()
        add("market_positive_prices", invalid == 0, f"invalid_rows={invalid}")
        bad_range = ((market["high"] < market[["open", "close", "low"]].max(axis=1)) | (market["low"] > market[["open", "close", "high"]].min(axis=1))).sum()
        add("market_ohlc_range", bad_range == 0, f"invalid_rows={bad_range}")
    for path in factor_paths:
        frame = pd.read_parquet(path)
        required = {"date", "available_at", "instrument", "factor_id", "value"}
        label = f"factor:{path.name}"
        add(label + ":schema", not required.difference(frame.columns), str(sorted(required.difference(frame.columns))))
        if not required.difference(frame.columns):
            dates = pd.to_datetime(frame["date"])
            available = pd.to_datetime(frame["available_at"])
            future = (available > dates).sum()
            duplicate = frame.duplicated(["date", "instrument", "factor_id"]).sum()
            nonfinite = (~np.isfinite(pd.to_numeric(frame["value"], errors="coerce"))).sum()
            add(label + ":no_future", future == 0, f"violations={future}")
            add(label + ":unique_key", duplicate == 0, f"duplicates={duplicate}")
            add(label + ":finite", nonfinite == 0, f"invalid_values={nonfinite}")
    if futures_path is not None:
        futures = pd.read_parquet(futures_path)
        required = {"date", "nav_index"}
        has_contract = "contract" in futures or "selected_contract" in futures
        missing = required.difference(futures.columns)
        add("ic_schema", not missing and has_contract, str(sorted(missing)) + f"; contract_column={has_contract}")
        if not missing and has_contract:
            duplicate = futures.duplicated(["date"]).sum()
            add("ic_unique_date", duplicate == 0, f"duplicates={duplicate}")
            add("ic_positive_nav", bool((futures["nav_index"] > 0).all()), f"rows={len(futures)}")
    return {
        "schema": "aster-research-verification-v1",
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "inputs": {
            "market": {"path": str(market_path.resolve()), "sha256": sha256_file(market_path)},
            "factors": [{"path": str(path.resolve()), "sha256": sha256_file(path)} for path in factor_paths],
            "futures": None if futures_path is None else {"path": str(futures_path.resolve()), "sha256": sha256_file(futures_path)},
        },
    }


def build_experiment_matrix(registry_path: Path) -> dict:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    approved = [item for item in registry["factors"] if item["approval_status"] == "approved"]
    groups = sorted({item["factor_group"] for item in approved})
    baseline = [item for item in ("conventional_reversal", "conventional_low_vol") if item in groups]
    experiments = [{"experiment_id": "baseline", "groups": baseline, "purpose": "fixed non-AI baseline"}]
    for group in groups:
        if group not in baseline:
            experiments.append({
                "experiment_id": f"baseline_plus_{group}", "groups": baseline + [group],
                "purpose": "one-group marginal contribution",
            })
    experiments.append({"experiment_id": "all_approved", "groups": groups, "purpose": "upper-complexity comparison"})
    return {
        "schema": "aster-experiment-matrix-v1", "registry_version": registry["version"],
        "fixed_controls": ["same PIT universe", "same labels", "same costs", "same optimizer profile", "same rebalance dates"],
        "experiments": experiments,
    }


def attribute_backtest(daily_path: Path, metrics_path: Path | None = None) -> dict:
    daily = pd.read_csv(daily_path)
    stock = float(daily["stock_return"].sum())
    futures = float(daily["futures_return_contribution"].sum())
    cost = float(daily["cost_fraction"].sum())
    total = float(daily["return"].sum())
    payload = {
        "schema": "aster-return-attribution-v1",
        "arithmetic_return": total,
        "stock_contribution": stock,
        "futures_contribution": futures,
        "cost_drag": -cost,
        "reconciliation_residual": total - stock - futures + cost,
        "rebalance_count": int(daily["rebalanced"].astype(str).str.lower().eq("true").sum()),
        "average_gross_exposure": float(daily["gross_exposure"].mean()),
        "maximum_absolute_estimated_beta": float(daily["estimated_net_beta"].abs().max()),
    }
    if metrics_path and metrics_path.exists():
        payload["reported_metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
    return payload


def write_research_report(
    *, output_path: Path, verification: dict, experiments: dict,
    attribution: dict | None, diagnostics_path: Path | None = None,
) -> None:
    lines = [
        "# Aster research run report", "",
        f"Input verification: **{'PASS' if verification['passed'] else 'FAIL'}**", "",
        "## Data checks", "",
        "| Check | Result | Detail |", "|---|---:|---|",
    ]
    for item in verification["checks"]:
        lines.append(f"| {item['check']} | {'PASS' if item['passed'] else 'FAIL'} | {item['detail']} |")
    lines.extend(["", "## Experiment matrix", ""])
    for item in experiments["experiments"]:
        lines.append(f"- `{item['experiment_id']}`: {', '.join(item['groups']) or '(none)'} — {item['purpose']}")
    if attribution is not None:
        lines.extend([
            "", "## Return attribution", "",
            f"- Stock contribution: {attribution['stock_contribution']:.6f}",
            f"- IC futures contribution: {attribution['futures_contribution']:.6f}",
            f"- Cost drag: {attribution['cost_drag']:.6f}",
            f"- Reconciliation residual: {attribution['reconciliation_residual']:.3e}",
        ])
    if diagnostics_path and diagnostics_path.exists():
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        lines.extend(["", "## Factor diagnostics", "", "| Factor | Coverage | Rank IC | IC IR |", "|---|---:|---:|---:|"])
        for item in diagnostics["factors"]:
            lines.append(f"| {item['factor_id']} | {item['coverage']:.3f} | {item['rank_ic_mean']:.4f} | {item['rank_ic_ir']:.3f} |")
    lines.extend(["", "> This report is a research artifact, not an investment recommendation.", ""])
    write_bytes_atomic(output_path, "\n".join(lines).encode("utf-8"))


def build_release_manifest(paths: list[Path], output_path: Path) -> dict:
    files = []
    for path in paths:
        if path.exists() and path.is_file():
            files.append({"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    payload = {"schema": "aster-research-release-v1", "files": files}
    write_json_atomic(output_path, payload)
    return payload
