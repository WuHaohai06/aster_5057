"""Command-line entry points for the initial Aster data adapters."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from .qlib_collectors import QlibCollectorAdapter


def _print_artifact(artifact) -> None:
    for key, value in asdict(artifact).items():
        print(f"{key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect source data through version-locked Qlib adapters")
    subparsers = parser.add_subparsers(dest="command", required=True)

    csi500 = subparsers.add_parser("csi500")
    csi500.add_argument("--as-of", required=True)

    pit = subparsers.add_parser("pit")
    pit.add_argument("--symbol", required=True, help="Qlib symbol such as 600519.ss")
    pit.add_argument("--start", required=True)
    pit.add_argument("--end", required=True)

    yahoo = subparsers.add_parser("yahoo")
    yahoo.add_argument("--symbol", required=True, help="Yahoo symbol such as 600519.SS")
    yahoo.add_argument("--start", required=True)
    yahoo.add_argument("--end", required=True)

    subparsers.add_parser("sample")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    adapter = QlibCollectorAdapter()

    if args.command == "csi500":
        _print_artifact(adapter.collect_csi500_snapshot(args.as_of))
    elif args.command == "pit":
        _print_artifact(adapter.collect_pit_symbol(args.symbol, args.start, args.end))
    elif args.command == "yahoo":
        _print_artifact(adapter.collect_yahoo_daily(args.symbol, args.start, args.end))
    elif args.command == "sample":
        artifacts = [
            adapter.collect_csi500_snapshot("2024-06-28"),
            adapter.collect_pit_symbol("600519.ss", "2023-01-01", "2023-12-31"),
            adapter.collect_yahoo_daily("600519.SS", "2024-01-01", "2024-01-15"),
        ]
        for artifact in artifacts:
            _print_artifact(artifact)
            print()


if __name__ == "__main__":
    main()

