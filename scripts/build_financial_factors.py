from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.factor_store import build_financial_factors


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical PIT financial factors")
    parser.add_argument("--pit-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_financial_factors(
        pit_root=args.pit_root, output_root=args.output_root
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
