"""Generate auditable filing-text factors from page-addressable documents."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .io import sha256_file, write_json_atomic


POSITIVE = ("增长", "提升", "改善", "领先", "突破", "扩张", "充足", "稳健", "景气")
NEGATIVE = ("下降", "下滑", "承压", "亏损", "减值", "不确定", "风险", "诉讼", "处罚")
RISK = ("风险", "不确定", "波动", "减值", "违约", "诉讼", "处罚", "依赖")
LLM_FIELDS = (
    "management_outlook", "demand_strength", "margin_pressure", "capex_intensity", "risk_level"
)


def _canonical_row(document: dict, factor_id: str, value: float, origin: str) -> dict:
    available = pd.Timestamp(document["available_at"])
    return {
        "date": available.normalize(), "available_at": available.normalize(),
        "instrument": document["instrument"], "factor_id": factor_id,
        "factor_group": "financial_text", "value": float(value), "origin": origin,
        "source_id": "filing:" + document["source_sha256"],
        "version": "aster-filing-text-v1",
    }


def _deterministic(document: dict) -> tuple[list[dict], dict]:
    text = "\n".join(page["text"] for page in document["pages"])
    compact = re.sub(r"\s+", "", text)
    length = max(1, len(compact))
    positive = sum(compact.count(word) for word in POSITIVE)
    negative = sum(compact.count(word) for word in NEGATIVE)
    risk = sum(compact.count(word) for word in RISK)
    rows = [
        _canonical_row(document, "text_log_characters", math.log1p(length), "filing_text_deterministic"),
        _canonical_row(document, "text_tone_balance", (positive - negative) / max(1, positive + negative), "filing_text_deterministic"),
        _canonical_row(document, "text_risk_density_10k", risk * 10000.0 / length, "filing_text_deterministic"),
    ]
    evidence = {
        "method": "deterministic_keyword_v1", "characters": length,
        "positive_hits": positive, "negative_hits": negative, "risk_hits": risk,
        "quality": document["quality"],
    }
    return rows, evidence


def _llm_payload(document: dict, *, api_key: str, base_url: str, model: str) -> tuple[list[dict], dict]:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai is required for --mode llm") from exc
    pages = document["pages"]
    keyword_pages = [
        page for page in pages
        if any(word in page["text"] for word in ("经营情况", "未来发展", "风险因素", "管理层讨论", "现金流"))
    ]
    chosen: dict[int, dict] = {page["page"]: page for page in pages[:8]}
    chosen.update({page["page"]: page for page in keyword_pages[:24]})
    excerpts = []
    total = 0
    for page in chosen.values():
        excerpt = page["text"][:5000]
        if total + len(excerpt) > 60000:
            break
        excerpts.append(f"[PAGE {page['page']}]\n{excerpt}")
        total += len(excerpt)
    prompt = (
        "You are scoring a Chinese listed-company filing using only supplied evidence. "
        "Return one JSON object with keys management_outlook, demand_strength, "
        "margin_pressure, capex_intensity, risk_level. Each value must be either null or "
        "an object {score: number from -1 to 1, citations: [{page: integer, reason: string}]}. "
        "Use null when evidence is insufficient. Never infer facts outside the excerpts.\n\n"
        + "\n\n".join(excerpts)
    )
    response = OpenAI(api_key=api_key, base_url=base_url).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    valid_pages = {page["page"] for page in pages}
    rows = []
    validated: dict[str, Any] = {}
    for field in LLM_FIELDS:
        item = payload.get(field)
        if item is None:
            validated[field] = None
            continue
        score = float(item["score"])
        if not -1.0 <= score <= 1.0:
            raise ValueError(f"{field} score outside [-1, 1]")
        citations = item.get("citations") or []
        if not citations or any(int(citation["page"]) not in valid_pages for citation in citations):
            raise ValueError(f"{field} lacks valid page citations")
        validated[field] = {"score": score, "citations": citations}
        rows.append(_canonical_row(document, "llm_" + field, score, "filing_text_llm"))
    return rows, {
        "method": "deepseek_structured_filing_v1", "model": model,
        "validated_scores": validated, "raw_response": raw,
    }


def build_filing_text_factors(
    *, parsed_root: Path, output_root: Path, mode: str = "deterministic",
    api_key: str | None = None, base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-flash", limit: int | None = None,
) -> dict:
    documents = sorted(parsed_root.rglob("document.json"))
    if limit is not None:
        documents = documents[:limit]
    if not documents:
        raise RuntimeError(f"no parsed filing documents under {parsed_root}")
    if mode not in {"deterministic", "llm"}:
        raise ValueError("mode must be deterministic or llm")
    if mode == "llm" and not api_key:
        raise ValueError("API key is required for LLM mode")
    rows = []
    evidence_root = output_root / "evidence"
    failures = 0
    for path in documents:
        document = json.loads(path.read_text(encoding="utf-8"))
        try:
            if mode == "llm":
                document_rows, evidence = _llm_payload(
                    document, api_key=str(api_key), base_url=base_url, model=model
                )
            else:
                document_rows, evidence = _deterministic(document)
            rows.extend(document_rows)
            write_json_atomic(evidence_root / f"{document['source_sha256']}.{mode}.json", {
                "source_document": str(path.resolve()), "source_sha256": document["source_sha256"],
                **evidence,
            })
        except Exception as exc:
            failures += 1
            write_json_atomic(evidence_root / f"{document['source_sha256']}.{mode}.error.json", {
                "source_document": str(path.resolve()), "error": f"{type(exc).__name__}: {exc}",
            })
    if not rows:
        raise RuntimeError("no filing text factors were produced")
    frame = pd.DataFrame(rows).sort_values(["date", "instrument", "factor_id"])
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"filing_text_factors_{mode}.parquet"
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)
    manifest = {
        "dataset": "aster-filing-text-factors-v1", "mode": mode,
        "documents": len(documents), "rows": len(frame), "failures": failures,
        "factor_ids": sorted(frame["factor_id"].unique()), "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "guardrail": "LLM scores require page citations and never directly set portfolio weights",
    }
    write_json_atomic(output_root / f"filing_text_manifest_{mode}.json", manifest)
    return manifest
