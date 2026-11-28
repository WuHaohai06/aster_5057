from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_council.refresh import (  # noqa: E402
    DEFAULT_MARKET,
    DEFAULT_POLICY,
    refresh_quarter_evidence,
    run_council,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild the Factor Council evidence chain for quarter cutoffs"
    )
    parser.add_argument("--cutoff", action="append", required=True, help="YYYY-MM-DD (repeatable)")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "council" / "quarterly_evidence",
    )
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--library-root", type=Path, default=PROJECT_ROOT / "data/curated/factor_library")
    parser.add_argument(
        "--council-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "council" / "real_runs",
        help="Where run_factor_council.ps1 stores decision packets",
    )
    parser.add_argument("--run-council", action="store_true")
    parser.add_argument("--skip-council", action="store_true", help="Only build evidence and packets")
    args = parser.parse_args()

    results = []
    for cutoff in args.cutoff:
        summary = refresh_quarter_evidence(
            cutoff=cutoff,
            output_root=args.output_root,
            project_root=PROJECT_ROOT,
            market_path=args.market,
            policy_path=args.policy,
            library_root=args.library_root,
        )
        if args.run_council and not args.skip_council:
            summary["council"] = run_council(
                packet_path=Path(summary["packet_path"]),
                output_root=args.council_output,
            )
        results.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({"cutoffs": args.cutoff, "packets": [r["packet_path"] for r in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
