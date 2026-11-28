"""Translate factor narrative fields into Simplified Chinese (cached)."""

from __future__ import annotations

import argparse
import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from aster_council.llm import DeepSeekCouncilClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = PROJECT_ROOT / "data/console/factor_translations.json"
SNAPSHOT_URL = "http://127.0.0.1:8765/api/snapshot"

FIELDS = ("description", "hypothesis", "mechanism", "expectedDirection", "falsificationCriteria")
FIELD_ZH = {
    "description": "description_zh",
    "hypothesis": "hypothesis_zh",
    "mechanism": "mechanism_zh",
    "expectedDirection": "expected_direction_zh",
    "falsificationCriteria": "falsification_criteria_zh",
}

SYSTEM_PROMPT = (
    "You translate quantitative-finance factor documentation into Simplified Chinese. "
    "Keep factor ids, formulas, tickers, numbers and technical terms accurate; translate "
    "naturally and concisely. Return JSON only."
)


def load_snapshot() -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(SNAPSHOT_URL, timeout=30) as response:
            return json.load(response)["factors"]
    except Exception:
        catalog = json.loads(
            (PROJECT_ROOT / "data/curated/factor_library/catalog.json").read_text(encoding="utf-8")
        )
        return catalog["factors"]


def translate(client: DeepSeekCouncilClient, factor: dict[str, Any]) -> dict[str, str]:
    payload = {
        field: (factor.get(field) if field == "falsificationCriteria" else str(factor.get(field) or "").strip())
        for field in FIELDS
    }
    user_prompt = (
        "Translate the following factor documentation into Simplified Chinese. "
        "Return JSON with keys description, hypothesis, mechanism, expectedDirection, "
        "falsificationCriteria (array of strings, same length).\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    result = client.complete_json(
        call_id=f"factor-zh-{factor.get('id') or factor.get('factor_id')}",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )
    body = result.payload
    translated = {}
    for field in FIELDS:
        if field == "falsificationCriteria":
            value = body.get(field)
            translated[FIELD_ZH[field]] = value if isinstance(value, list) else payload[field]
        else:
            value = str(body.get(field) or "").strip()
            translated[FIELD_ZH[field]] = value or payload[field]
    return translated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    factors = load_snapshot()
    existing: dict[str, dict[str, str]] = {}
    if OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    lock = threading.Lock()
    client = DeepSeekCouncilClient()

    pending = [
        factor
        for factor in factors
        if str(factor.get("id") or "") not in existing
        or "falsification_criteria_zh" not in existing.get(str(factor.get("id") or ""), {})
    ]
    if args.limit:
        pending = pending[: args.limit]
    print(f"factors: {len(factors)}, pending: {len(pending)}", flush=True)

    def run(factor: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        return factor, translate(client, factor)

    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for factor, translated in executor.map(run, pending):
            factor_id = str(factor.get("id") or "")
            with lock:
                existing[factor_id] = translated
                OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
                OUT_PATH.write_text(
                    json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            print(f"done {factor_id} {factor.get('name','')}", flush=True)

    print(f"complete: {len(pending)} translated, {failures} failures", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
