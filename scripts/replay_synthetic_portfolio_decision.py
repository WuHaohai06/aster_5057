"""Replay the synthetic portfolio pipeline with a validated Council decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aster_portfolio.council import PortfolioCouncilDecision
from aster_portfolio.schemas import default_profiles
from aster_portfolio.smoke import write_smoke_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    decision_bytes = args.decision.read_bytes()
    decision = PortfolioCouncilDecision.model_validate_json(decision_bytes)
    if decision.selected_profile_id not in default_profiles():
        raise ValueError("Council decision selected an unknown profile")
    result = write_smoke_artifacts(
        args.output_root, profile_id=decision.selected_profile_id
    )
    link = {
        "source_council_run_id": decision.run_id,
        "source_packet_digest": decision.packet_digest,
        "source_decision_sha256": hashlib.sha256(decision_bytes).hexdigest(),
        "selected_profile_id": decision.selected_profile_id,
        "council_fallback_used": decision.fallback_used,
    }
    link_text = json.dumps(link, indent=2, sort_keys=True) + "\n"
    link_path = args.output_root / "council_link.json"
    link_path.write_bytes(link_text.encode("utf-8"))
    manifest_path = args.output_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_council"] = link
    manifest["files"]["council_link.json"] = hashlib.sha256(
        link_text.encode("utf-8")
    ).hexdigest()
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    result.update(link)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
