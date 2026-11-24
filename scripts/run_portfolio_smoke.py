"""Run the deterministic synthetic portfolio pipeline and write audit artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aster_portfolio.smoke import write_smoke_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--profile", default="balanced")
    args = parser.parse_args()
    print(
        json.dumps(
            write_smoke_artifacts(args.output_root, profile_id=args.profile),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
