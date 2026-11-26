"""Build, validate, inspect and govern the unified Aster factor library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.factor_library import (
    LifecycleStatus,
    build_factor_library,
    evaluate_quantaalpha_candidates,
    export_council_inputs,
    load_catalog,
    set_factor_status,
    validate_factor_library,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/curated/factor_library",
    )
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--quanta-library", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("--shallow", action="store_true")
    listing = commands.add_parser("list")
    listing.add_argument("--status", choices=[item.value for item in LifecycleStatus])
    show = commands.add_parser("show")
    show.add_argument("factor_id")
    status = commands.add_parser("set-status")
    status.add_argument("factor_id")
    status.add_argument("status", choices=[item.value for item in LifecycleStatus])
    status.add_argument("--reason", required=True)
    status.add_argument("--actor", default="manual")
    export = commands.add_parser("export-council")
    export.add_argument("--mode", choices=["research", "showcase"], default="research")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--group", action="append", default=[])
    quanta = commands.add_parser("evaluate-quanta")
    quanta.add_argument(
        "--market", type=Path,
        default=PROJECT_ROOT / "data/curated/market/daily.parquet",
    )
    quanta.add_argument(
        "--evidence-root", type=Path,
        default=PROJECT_ROOT / "data/council/quanta_evidence",
    )
    quanta.add_argument("--as-of", required=True)
    quanta.add_argument("--horizon", type=int, default=20)
    quanta.add_argument("--min-coverage", type=float, default=0.75)
    quanta.add_argument("--min-observations", type=int, default=24)
    quanta.add_argument("--group", action="append", default=[])
    all_factors = commands.add_parser("evaluate-all")
    all_factors.add_argument(
        "--market", type=Path,
        default=PROJECT_ROOT / "data/curated/market/daily.parquet",
    )
    all_factors.add_argument(
        "--evidence-root", type=Path,
        default=PROJECT_ROOT / "data/council/factor_evidence",
    )
    all_factors.add_argument("--as-of", required=True)
    all_factors.add_argument("--horizon", type=int, default=20)
    all_factors.add_argument("--min-coverage", type=float, default=0.75)
    all_factors.add_argument("--min-observations", type=int, default=24)
    all_factors.add_argument("--group", action="append", default=[])
    origin = commands.add_parser("evaluate-origin")
    origin.add_argument("--origin", action="append", required=True)
    origin.add_argument(
        "--market", type=Path,
        default=PROJECT_ROOT / "data/curated/market/daily.parquet",
    )
    origin.add_argument(
        "--evidence-root", type=Path,
        default=PROJECT_ROOT / "data/council/factor_evidence",
    )
    origin.add_argument("--as-of", required=True)
    origin.add_argument("--horizon", type=int, default=20)
    origin.add_argument("--min-coverage", type=float, default=0.75)
    origin.add_argument("--min-observations", type=int, default=24)
    origin.add_argument("--group", action="append", default=[])
    return root


def main() -> None:
    args = parser().parse_args()
    output_root = args.output_root.resolve()
    if args.command == "build":
        catalog = build_factor_library(
            project_root=PROJECT_ROOT,
            output_root=output_root,
            quanta_library_path=args.quanta_library,
        )
        payload = {
            "status": "ok",
            "catalog": str((output_root / "catalog.json").resolve()),
            "catalog_digest": catalog.catalog_digest,
            "factor_count": len(catalog.factors),
            "counts_by_status": {},
        }
        for factor in catalog.factors:
            key = factor.lifecycle_status.value
            payload["counts_by_status"][key] = payload["counts_by_status"].get(key, 0) + 1
    elif args.command == "validate":
        payload = validate_factor_library(
            project_root=PROJECT_ROOT,
            catalog_path=output_root / "catalog.json",
            deep=not args.shallow,
        )
    elif args.command == "set-status":
        catalog = set_factor_status(
            output_root=output_root,
            factor_id=args.factor_id,
            new_status=LifecycleStatus(args.status),
            reason=args.reason,
            actor=args.actor,
        )
        factor = next(item for item in catalog.factors if item.factor_id == args.factor_id)
        payload = {
            "status": "ok",
            "factor_id": factor.factor_id,
            "lifecycle_status": factor.lifecycle_status.value,
            "catalog_digest": catalog.catalog_digest,
        }
    elif args.command == "export-council":
        payload = export_council_inputs(
            catalog_path=output_root / "catalog.json",
            output_root=args.output,
            mode=args.mode,
            groups=set(args.group) if args.group else None,
        )
    elif args.command in {"evaluate-quanta", "evaluate-all", "evaluate-origin"}:
        origins = (
            None
            if args.command == "evaluate-all"
            else tuple(args.origin)
            if args.command == "evaluate-origin"
            else ("quantaalpha",)
        )
        payload = evaluate_quantaalpha_candidates(
            project_root=PROJECT_ROOT,
            catalog_path=output_root / "catalog.json",
            market_path=args.market,
            evidence_root=args.evidence_root,
            as_of=args.as_of,
            horizon=args.horizon,
            min_coverage=args.min_coverage,
            min_observations=args.min_observations,
            origins=origins,
            groups=set(args.group) if args.group else None,
        )
    else:
        catalog = load_catalog(output_root / "catalog.json")
        factors = catalog.factors
        if args.command == "show":
            factor = next((item for item in factors if item.factor_id == args.factor_id), None)
            if factor is None:
                raise KeyError(f"unknown factor_id: {args.factor_id}")
            payload = factor.model_dump(mode="json")
        else:
            if args.status:
                factors = [item for item in factors if item.lifecycle_status.value == args.status]
            payload = {
                "factor_count": len(factors),
                "factors": [
                    {
                        "factor_id": item.factor_id,
                        "display_name": item.display_name,
                        "family": item.family,
                        "status": item.lifecycle_status.value,
                        "research_eligible": item.research_eligible,
                        "demo_eligible": item.demo_eligible,
                        "rows": item.artifact.rows,
                    }
                    for item in factors
                ],
            }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.command == "validate" and not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
