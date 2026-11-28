"""Translate council ballots and packet mechanisms into Simplified Chinese (cached)."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from aster_council.llm import DeepSeekCouncilClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = PROJECT_ROOT / "data/console/council_evidence_cache.json"
RUN_ROOTS = ("real_runs", "showcase_runs")

SYSTEM_PROMPT = (
    "You translate quantitative investment committee materials into Simplified Chinese. "
    "Keep group ids, factor ids, numbers, percentages and technical terms accurate. "
    "Preserve the JSON structure exactly. Return JSON only."
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cache: dict[str, Any] = load_json(CACHE_PATH) if CACHE_PATH.exists() else {}
    lock = threading.Lock()
    client = DeepSeekCouncilClient()

    ballot_jobs: list[dict[str, Any]] = []
    packet_jobs: list[dict[str, Any]] = []
    for root_name in RUN_ROOTS:
        root = PROJECT_ROOT / f"data/council/{root_name}"
        if not root.exists():
            continue
        for run_dir in sorted(root.iterdir()):
            if not run_dir.is_dir():
                continue
            ballots_dir = run_dir / "ballots"
            if ballots_dir.exists():
                for path in sorted(ballots_dir.glob("*.json")):
                    ballot = load_json(path)
                    votes = ballot.get("votes", [])
                    if ballot.get("summary_zh") and all(v.get("rationale_zh") for v in votes):
                        continue
                    payload = {
                        "summary": ballot.get("summary", ""),
                        "votes": [
                            {
                                "group_id": vote.get("group_id"),
                                "rationale": vote.get("rationale", ""),
                                "risks": vote.get("risks", []),
                            }
                            for vote in votes
                        ],
                        "dissent_conditions": ballot.get("dissent_conditions", []),
                    }
                    ballot_jobs.append({"path": path, "payload": payload})
            packet_path = run_dir / "packet.json"
            if packet_path.exists():
                packet = load_json(packet_path)
                for group in packet.get("factor_groups", []):
                    factors = group.get("factors", [])
                    if factors and all(f.get("economic_hypothesis_zh") for f in factors):
                        continue
                    payload = {
                        "group_id": group.get("group_id"),
                        "factors": [
                            {
                                "factor_id": f.get("factor_id"),
                                "economic_hypothesis": f.get("economic_hypothesis", ""),
                                "mechanism_explanation": f.get("mechanism_explanation", ""),
                                "expected_direction": f.get("expected_direction", ""),
                                "falsification_criteria": f.get("falsification_criteria", []),
                            }
                            for f in factors
                        ],
                    }
                    packet_jobs.append({"path": packet_path, "group_id": group.get("group_id"), "payload": payload})

    if args.limit:
        ballot_jobs = ballot_jobs[: args.limit]
        packet_jobs = packet_jobs[: args.limit]
    print(f"ballots: {len(ballot_jobs)}, groups: {len(packet_jobs)}", flush=True)

    def run(job: dict[str, Any], kind: str) -> tuple[dict[str, Any], str, Any]:
        key = f"{kind}:{digest(job['payload'])}"
        with lock:
            cached = cache.get(key)
        if cached is not None:
            return job, key, cached
        result = client.complete_json(
            call_id=f"{kind}-{key[:16]}",
            system_prompt=SYSTEM_PROMPT,
            user_prompt="Translate every string value into Simplified Chinese, preserving keys and arrays. Return JSON only.\n\n" + json.dumps(job["payload"], ensure_ascii=False),
        )
        return job, key, result.payload

    failures = 0
    for job, key, translated in executor_map(run, ballot_jobs, "ballot", args.workers):
        ballot = load_json(job["path"])
        ballot["summary_zh"] = translated.get("summary", ballot.get("summary", ""))
        votes = ballot.get("votes", [])
        for index, vote in enumerate(votes):
            translated_vote = (translated.get("votes") or [])[index] if index < len(translated.get("votes") or []) else {}
            vote["rationale_zh"] = translated_vote.get("rationale", vote.get("rationale", ""))
            vote["risks_zh"] = translated_vote.get("risks", vote.get("risks", []))
        ballot["dissent_conditions_zh"] = translated.get("dissent_conditions", ballot.get("dissent_conditions", []))
        save_json(job["path"], ballot)
        with lock:
            cache[key] = translated
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            save_json(CACHE_PATH, cache)
        print(f"done ballot {job['path'].parent.parent.name}/{job['path'].name}", flush=True)

    for job, key, translated in executor_map(run, packet_jobs, "group", args.workers):
        packet = load_json(job["path"])
        group = next((g for g in packet.get("factor_groups", []) if g.get("group_id") == job["group_id"]), None)
        if group is None:
            continue
        translated_factors = {f.get("factor_id"): f for f in (translated.get("factors") or [])}
        for factor in group.get("factors", []):
            item = translated_factors.get(factor.get("factor_id")) or {}
            factor["economic_hypothesis_zh"] = item.get("economic_hypothesis", factor.get("economic_hypothesis", ""))
            factor["mechanism_explanation_zh"] = item.get("mechanism_explanation", factor.get("mechanism_explanation", ""))
            factor["expected_direction_zh"] = item.get("expected_direction", factor.get("expected_direction", ""))
            factor["falsification_criteria_zh"] = item.get("falsification_criteria", factor.get("falsification_criteria", []))
        save_json(job["path"], packet)
        with lock:
            cache[key] = translated
            save_json(CACHE_PATH, cache)
        print(f"done group {job['path'].parent.name}/{job['group_id']}", flush=True)

    print(f"complete, failures={failures}", flush=True)
    return 0


def executor_map(fn, jobs, kind, workers):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for result in executor.map(lambda job: fn(job, kind), jobs):
            yield result


if __name__ == "__main__":
    raise SystemExit(main())
