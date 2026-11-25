from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.industry_snapshot import build_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a static CNInfo industry snapshot")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-11-20")
    parser.add_argument("--snapshot-date", default="2026-11-25")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    result = build_snapshot(
        project_root=PROJECT_ROOT,
        start=args.start,
        end=args.end,
        snapshot_date=args.snapshot_date,
        workers=args.workers,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
