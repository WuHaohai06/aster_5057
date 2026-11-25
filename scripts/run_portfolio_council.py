"""Run the AI portfolio-policy Council from a validated packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aster_council.llm import DeepSeekCouncilClient, StaticCouncilClient
from aster_portfolio.council import PortfolioCouncilOrchestrator, PortfolioCouncilPacket


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--static-responses", type=Path)
    args = parser.parse_args()
    packet = PortfolioCouncilPacket.model_validate_json(args.packet.read_text(encoding="utf-8"))
    if args.static_responses:
        client = StaticCouncilClient(
            json.loads(args.static_responses.read_text(encoding="utf-8"))
        )
    else:
        client = DeepSeekCouncilClient(model=args.model, base_url=args.base_url)
    decision, run_dir = PortfolioCouncilOrchestrator(client).run(packet, args.output_root)
    print(
        json.dumps(
            {
                "status": decision.status,
                "mode": decision.mode.value,
                "uses_hindsight": decision.uses_hindsight,
                "selected_profile_id": decision.selected_profile_id,
                "industry_overweights": decision.industry_overweights,
                "industry_underweights": decision.industry_underweights,
                "industry_active_tilt": decision.industry_active_tilt,
                "fallback_used": decision.fallback_used,
                "fallback_reason": decision.fallback_reason,
                "run_dir": str(run_dir.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
