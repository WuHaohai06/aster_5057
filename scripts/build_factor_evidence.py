from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.factor_evidence import build_market_context, build_market_factors, evaluate_factors


def main() -> None:
    parser = argparse.ArgumentParser(description="Build real factor diagnostics and Council market evidence")
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--factor", type=Path, action="append", default=[])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--skip-market-factors", action="store_true")
    args = parser.parse_args()
    factor_paths = list(args.factor)
    if not args.skip_market_factors:
        baseline_path = args.output_root / "market_factors.parquet"
        build_market_factors(market_path=args.market, output_path=baseline_path, as_of=args.as_of)
        factor_paths.insert(0, baseline_path)
    if not factor_paths:
        raise SystemExit("at least one factor path is required")
    registry, diagnostics = evaluate_factors(
        factor_paths=factor_paths, market_path=args.market, output_root=args.output_root,
        as_of=args.as_of, horizon=args.horizon,
    )
    market = build_market_context(
        market_path=args.market, as_of=args.as_of,
        output_path=args.output_root / "market_state.json",
    )
    print(json.dumps({
        "factors": len(registry["factors"]), "diagnostics": len(diagnostics["factors"]),
        "market_as_of": market["as_of_close"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
