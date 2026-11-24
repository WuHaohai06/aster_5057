"""Immutable, hash-addressed audit artifacts for Council runs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel

from .schemas import CouncilDecision, DecisionPacket, LLMCallRecord, ReviewerBallot


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _model_payload(model: BaseModel) -> dict:
    return model.model_dump(mode="json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_run_artifacts(
    *,
    output_root: Path,
    packet: DecisionPacket,
    ballots: dict[str, ReviewerBallot],
    calls: dict[str, LLMCallRecord],
    decision: CouncilDecision,
) -> Path:
    run_dir = output_root / decision.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(run_dir / "packet.json", _model_payload(packet))
    for role, ballot in sorted(ballots.items()):
        _write_json(run_dir / "ballots" / f"{role}.json", _model_payload(ballot))
    for call_id, call in sorted(calls.items()):
        _write_json(run_dir / "calls" / f"{call_id}.json", _model_payload(call))
    _write_json(run_dir / "decision.json", _model_payload(decision))

    artifact_paths = sorted(
        path for path in run_dir.rglob("*.json") if path.name != "manifest.json"
    )
    manifest = {
        "run_id": decision.run_id,
        "packet_digest": packet.packet_digest,
        "files": {
            str(path.relative_to(run_dir)).replace("\\", "/"): _sha256(path)
            for path in artifact_paths
        },
    }
    _write_json(run_dir / "manifest.json", manifest)
    return run_dir
