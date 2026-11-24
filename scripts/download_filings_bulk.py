from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.filing_pipeline import download_filings_bulk


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-download CSI500 PIT-union filings")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--report-types", default="annual")
    parser.add_argument("--verify-exchange", action="store_true")
    parser.add_argument("--request-delay", type=float, default=1.5)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    result = download_filings_bulk(
        project_root=args.project_root, universe_path=args.universe,
        start=args.start, end=args.end,
        report_types=[item.strip() for item in args.report_types.split(",") if item.strip()],
        verify_exchange=args.verify_exchange, request_delay=args.request_delay, limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
