from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.filing_pipeline import parse_filing_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse filing PDFs into page-addressable AI documents")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--minimum-chars-per-page", type=int, default=80)
    args = parser.parse_args()
    print(json.dumps(parse_filing_records(
        project_root=args.project_root, limit=args.limit,
        minimum_chars_per_page=args.minimum_chars_per_page,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
