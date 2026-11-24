from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.io import write_json_atomic
from aster_portfolio.research_ops import (
    attribute_backtest, build_experiment_matrix, build_release_manifest,
    verify_research_inputs, write_research_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and package an Aster research run")
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--factor", type=Path, action="append", required=True)
    parser.add_argument("--futures", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--backtest-root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    verification = verify_research_inputs(
        market_path=args.market, factor_paths=args.factor, futures_path=args.futures
    )
    experiments = build_experiment_matrix(args.registry)
    attribution = None
    if args.backtest_root:
        attribution = attribute_backtest(
            args.backtest_root / "daily.csv", args.backtest_root / "metrics.json"
        )
    verification_path = args.output_root / "verification.json"
    experiments_path = args.output_root / "experiment_matrix.json"
    attribution_path = args.output_root / "attribution.json"
    write_json_atomic(verification_path, verification)
    write_json_atomic(experiments_path, experiments)
    if attribution is not None:
        write_json_atomic(attribution_path, attribution)
    report_path = args.output_root / "research_report.md"
    write_research_report(
        output_path=report_path, verification=verification, experiments=experiments,
        attribution=attribution, diagnostics_path=args.diagnostics,
    )
    release_files = [verification_path, experiments_path, report_path, args.registry]
    if args.diagnostics:
        release_files.append(args.diagnostics)
    if attribution is not None:
        release_files.append(attribution_path)
    release = build_release_manifest(release_files, args.output_root / "release_manifest.json")
    print(json.dumps({
        "verification_passed": verification["passed"],
        "experiments": len(experiments["experiments"]), "release_files": len(release["files"]),
        "output_root": str(args.output_root.resolve()),
    }, ensure_ascii=False, indent=2))
    if not verification["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
