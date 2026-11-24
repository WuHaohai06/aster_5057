"""Command line interface for packet construction and Council execution."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .evidence import DecisionPacketBuilder, write_packet
from .llm import DeepSeekCouncilClient, StaticCouncilClient
from .orchestrator import CouncilOrchestrator
from .schemas import CouncilMode, DecisionPacket, FactorShowcaseDirective


def _date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-packet", help="build a point-in-time evidence packet")
    build.add_argument("--registry", type=Path, required=True)
    build.add_argument("--diagnostics", type=Path, required=True)
    build.add_argument("--market", type=Path, required=True)
    build.add_argument("--policy", type=Path, required=True)
    build.add_argument("--decision-at", type=_date, required=True)
    build.add_argument("--input-cutoff", type=_date, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument(
        "--mode", choices=[mode.value for mode in CouncilMode], default=CouncilMode.RESEARCH.value
    )
    build.add_argument("--showcase-directive", type=Path)

    run = subparsers.add_parser("run", help="run reviewers, chair and deterministic validation")
    run.add_argument("--packet", type=Path, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--model", default="deepseek-flash")
    run.add_argument("--base-url", default="https://api.deepseek.com")
    run.add_argument("--max-tokens", type=int, default=6000)
    run.add_argument("--static-responses", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "build-packet":
        mode = CouncilMode(args.mode)
        directive = (
            FactorShowcaseDirective.model_validate_json(
                args.showcase_directive.read_text(encoding="utf-8")
            )
            if args.showcase_directive
            else None
        )
        packet = DecisionPacketBuilder().build_from_files(
            registry_path=args.registry,
            diagnostics_path=args.diagnostics,
            market_path=args.market,
            policy_path=args.policy,
            decision_at=args.decision_at,
            input_cutoff=args.input_cutoff,
            mode=mode,
            showcase_directive=directive,
        )
        write_packet(packet, args.output)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "output": str(args.output.resolve()),
                    "packet_digest": packet.packet_digest,
                    "mode": packet.mode.value,
                    "candidate_groups": [group.group_id for group in packet.factor_groups],
                    "excluded_factors": packet.excluded_factors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    packet = DecisionPacket.model_validate_json(args.packet.read_text(encoding="utf-8"))
    if args.static_responses:
        responses = json.loads(args.static_responses.read_text(encoding="utf-8"))
        client = StaticCouncilClient(responses)
    else:
        client = DeepSeekCouncilClient(
            model=args.model, base_url=args.base_url, max_tokens=args.max_tokens
        )
    result = CouncilOrchestrator(client).run(packet, args.output_root)
    print(
        json.dumps(
            {
                "status": result.decision.status,
                "mode": result.decision.mode.value,
                "uses_hindsight": result.decision.uses_hindsight,
                "selected_groups": result.decision.selected_groups,
                "fallback_used": result.decision.fallback_used,
                "fallback_reason": result.decision.fallback_reason,
                "run_dir": str(result.run_dir.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
