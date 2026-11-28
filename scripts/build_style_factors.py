from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.style_factors import build_style_factors


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic CSI500 style factors")
    parser.add_argument(
        "--market",
        type=Path,
        default=PROJECT_ROOT / "data/curated/market/daily.parquet",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/curated/factors/style",
    )
    parser.add_argument("--sample-every", type=int, default=5)
    args = parser.parse_args()
    result = build_style_factors(
        market_path=args.market.resolve(),
        output_root=args.output_root.resolve(),
        sample_every=args.sample_every,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
