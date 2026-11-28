"""Audited DeepSeek Search API evidence collection for replay Councils."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class DeepSeekWebResearchCollector:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        count_per_query: int = 6,
        keep_per_query: int = 3,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY or OPENAI_API_KEY is required for web research")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.count_per_query = count_per_query
        self.keep_per_query = keep_per_query
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _queries(*, decision_at: date, candidate_groups: list[str]) -> list[str]:
        quarter = (decision_at.month - 1) // 3 + 1
        group_terms = " ".join(candidate_groups[:4])
        return [
            f"{decision_at.year} Q{quarter} 中证500 A股 宏观 政策 市场回顾",
            f"{decision_at.year} Q{quarter} 中国股市 流动性 波动 风险偏好",
            f"{decision_at.year} Q{quarter} A股 行业景气 因子风格 {group_terms}"[:128],
        ]

    def _search(self, query: str) -> list[dict[str, Any]]:
        body = json.dumps(
            {
                "query": query,
                "count": self.count_per_query,
                "ori_question": query,
                "need_content": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/v1/tools/search",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"DeepSeek search HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"DeepSeek search transport error: {error.reason}") from error
        return list(payload.get("results", []))

    def collect(
        self,
        *,
        node_id: str,
        decision_at: date,
        input_cutoff: date,
        mode: str,
        candidate_groups: list[str],
    ) -> dict[str, Any]:
        queries = self._queries(decision_at=decision_at, candidate_groups=candidate_groups)
        cutoff = datetime.combine(input_cutoff, time.max, tzinfo=timezone.utc)
        relevance_start = datetime.combine(
            decision_at - timedelta(days=365), time.min, tzinfo=timezone.utc
        )
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        errors: list[str] = []
        seen_urls: set[str] = set()
        for query in queries:
            try:
                results = self._search(query)
            except Exception as error:
                errors.append(f"{query}: {type(error).__name__}: {error}")
                continue
            kept = 0
            for result in results:
                url = str(result.get("url", "")).strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                published = _published_at(result.get("date"))
                if published is not None and published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                pit_eligible = published is not None and published.astimezone(timezone.utc) <= cutoff
                timely = published is not None and published.astimezone(timezone.utc) >= relevance_start
                high_quality = float(result.get("rerank_score") or 0.0) >= 1.5
                text_payload = {
                    "title": result.get("title"),
                    "snippet": result.get("snippet"),
                    "summary": result.get("summary"),
                }
                source = {
                    "evidence_id": f"web:{_digest({'url': url, 'date': result.get('date')})[:20]}",
                    "query": query,
                    "title": str(result.get("title", ""))[:300],
                    "url": url,
                    "site_name": result.get("site_name"),
                    "published_at": result.get("date"),
                    "snippet": str(result.get("snippet", ""))[:500],
                    "summary": str(result.get("summary", ""))[:800],
                    "authority": result.get("authority"),
                    "rerank_score": result.get("rerank_score"),
                    "pit_eligible": pit_eligible,
                    "timely": timely,
                    "content_hash": _digest(text_payload),
                }
                rejection_reason = None
                if not high_quality:
                    rejection_reason = "rerank score below 1.5"
                elif mode == "research" and not pit_eligible:
                    rejection_reason = "missing publication time" if published is None else "published after input cutoff"
                elif mode == "research" and not timely:
                    rejection_reason = "published more than 365 days before the quarterly decision"
                if rejection_reason:
                    source["rejection_reason"] = rejection_reason
                    rejected.append(source)
                    continue
                if kept < self.keep_per_query:
                    accepted.append(source)
                    kept += 1
        payload = {
            "schema": "aster-web-evidence-v1",
            "node_id": node_id,
            "decision_at": decision_at.isoformat(),
            "input_cutoff": input_cutoff.isoformat(),
            "mode": mode,
            "provider": "deepseek-search-api",
            "captured_at": _now(),
            "queries": queries,
            "accepted": accepted,
            "rejected": rejected,
            "errors": errors,
            "disclosure": (
                "Showcase web evidence may include sources published after the historical decision date."
                if mode != "research" else None
            ),
        }
        payload["evidence_digest"] = _digest(payload)
        return payload

