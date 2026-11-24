from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.factor_store import ingest_factor_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest QuantaAlpha factor output")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--factor-id")
    parser.add_argument("--origin", default="quantaalpha")
    args = parser.parse_args()
    print(json.dumps(ingest_factor_file(
        input_path=args.input, output_root=args.output_root,
        factor_id=args.factor_id, origin=args.origin,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
