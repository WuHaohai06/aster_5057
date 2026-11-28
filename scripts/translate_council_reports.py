"""Translate council outputs (narrative memos and council rationales) with caching."""

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
CACHE_PATH = PROJECT_ROOT / "data/console/translations_cache.json"

SYSTEM_PROMPT = (
    "You are a precise financial translator for an investment research platform. "
    "Translate faithfully, keep factor ids, tickers, numbers, percentages and "
    "technical terms unchanged, and preserve the original tone. Return JSON only."
)


def load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_key(text: str, target: str) -> str:
    return hashlib.sha256(f"{target}\n{text}".encode("utf-8")).hexdigest()


def translate(client: DeepSeekCouncilClient, text: str, target: str, call_id: str) -> str:
    language = "English" if target == "en" else "Simplified Chinese"
    user_prompt = (
        f"Translate the following text into {language}. Return JSON: {{\"translation\": str}}.\n\n"
        f"TEXT:\n{text}"
    )
    result = client.complete_json(
        call_id=call_id,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )
    translation = str(result.payload.get("translation") or "").strip()
    if not translation:
        raise RuntimeError(f"empty translation for {call_id}")
    return translation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="debug: only translate N jobs")
    args = parser.parse_args()

    cache = load_cache()
    cache_lock = threading.Lock()
    client = DeepSeekCouncilClient()

    jobs: list[dict[str, Any]] = []
    for run_id in ("narrative_monthly_v3", "narrative_v2"):
        reports_dir = PROJECT_ROOT / f"data/portfolio/narrative_demo/{run_id}/reports"
        for path in sorted(reports_dir.glob("*.json")) if reports_dir.exists() else []:
            payload = json.loads(path.read_text(encoding="utf-8"))
            memo = str(payload.get("memo") or "").strip()
            if memo and not payload.get("memo_en"):
                jobs.append({
                    "path": path,
                    "field": "memo_en",
                    "text": memo,
                    "target": "en",
                    "call_id": f"memo-en-{run_id}-{path.stem}",
                })

    decision_paths = []
    for root_name in ("real_runs", "showcase_runs"):
        root = PROJECT_ROOT / f"data/council/{root_name}"
        if root.exists():
            decision_paths.extend(sorted(root.glob("*/decision.json")))
    for path in decision_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rationale = str(payload.get("rationale") or "").strip()
        if rationale and not payload.get("rationale_zh"):
            jobs.append({
                "path": path,
                "field": "rationale_zh",
                "text": rationale,
                "target": "zh",
                "call_id": f"rationale-zh-{path.parent.name}",
            })

    if args.limit:
        jobs = jobs[: args.limit]
    print(f"jobs: {len(jobs)} (cache entries: {len(cache)})", flush=True)

    def run(job: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        key = cache_key(job["text"], job["target"])
        with cache_lock:
            cached = cache.get(key)
        if cached:
            return job, key, cached
        translation = translate(client, job["text"], job["target"], job["call_id"])
        return job, key, translation

    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for job, key, translation in executor.map(run, jobs):
            with cache_lock:
                cache[key] = translation
                save_cache(cache)
            payload = json.loads(job["path"].read_text(encoding="utf-8"))
            payload[job["field"]] = translation
            job["path"].write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"done {job['path'].parent.name}/{job['path'].name} -> {job['field']}", flush=True)

    print(f"complete: {len(jobs)} jobs, {failures} failures", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
