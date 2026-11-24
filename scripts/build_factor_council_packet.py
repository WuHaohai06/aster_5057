from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_council.evidence import DecisionPacketBuilder, write_packet
from aster_council.schemas import CouncilMode, FactorShowcaseDirective


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a point-in-time real Factor Council packet")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--decision-at", type=date.fromisoformat, required=True)
    parser.add_argument("--input-cutoff", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=[mode.value for mode in CouncilMode], default=CouncilMode.RESEARCH.value
    )
    parser.add_argument("--showcase-directive", type=Path)
    args = parser.parse_args()
    directive = (
        FactorShowcaseDirective.model_validate_json(
            args.showcase_directive.read_text(encoding="utf-8")
        )
        if args.showcase_directive
        else None
    )
    packet = DecisionPacketBuilder().build_from_files(
        registry_path=args.registry, diagnostics_path=args.diagnostics,
        market_path=args.market, policy_path=args.policy,
        decision_at=args.decision_at, input_cutoff=args.input_cutoff,
        mode=CouncilMode(args.mode), showcase_directive=directive,
    )
    write_packet(packet, args.output)
    print(json.dumps({
        "output": str(args.output.resolve()), "packet_digest": packet.packet_digest,
        "mode": packet.mode.value,
        "groups": [item.group_id for item in packet.factor_groups],
        "excluded": packet.excluded_factors,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
