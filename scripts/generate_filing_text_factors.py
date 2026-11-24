from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.filing_text_factors import build_filing_text_factors


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate auditable filing text factors")
    parser.add_argument("--parsed-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mode", choices=["deterministic", "llm"], default="deterministic")
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    result = build_filing_text_factors(
        parsed_root=args.parsed_root, output_root=args.output_root, mode=args.mode,
        api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url=args.base_url,
        model=args.model, limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
