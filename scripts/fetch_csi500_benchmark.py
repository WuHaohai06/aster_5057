"""Fetch ten-year CSI500 benchmark history through the vendored Qlib/Baostock stack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aster_data.qlib_collectors import QlibCollectorAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    adapter = QlibCollectorAdapter(args.project_root)
    adapter.raw_root = args.project_root / "data" / "raw" / "qlib_full"
    artifact = adapter.collect_baostock_index_daily("SH000905", args.start, args.end)
    print(
        json.dumps(
            {
                "status": "ok",
                "path": str(artifact.data_path),
                "rows": artifact.row_count,
                "sha256": artifact.sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
