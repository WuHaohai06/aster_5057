"""OpenAI-compatible and deterministic test clients for Council calls."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from .schemas import LLMCallRecord


@dataclass(frozen=True)
class StructuredLLMResult:
    payload: dict[str, Any]
    record: LLMCallRecord


class StructuredLLMError(RuntimeError):
    def __init__(self, message: str, record: LLMCallRecord) -> None:
        super().__init__(message)
        self.record = record


class StructuredLLM(Protocol):
    def complete_json(
        self, *, call_id: str, system_prompt: str, user_prompt: str
    ) -> StructuredLLMResult: ...


def _prompt_hash(system_prompt: str, user_prompt: str) -> str:
    return hashlib.sha256(f"{system_prompt}\n---\n{user_prompt}".encode("utf-8")).hexdigest()


def _extract_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("LLM response contains no JSON object")
        parsed = json.loads(text[start:end])
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


class DeepSeekCouncilClient:
    DEFAULT_MAX_TOKENS = 20000
    RETRY_MAX_TOKENS = 32000

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        from openai import OpenAI

        key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY or OPENAI_API_KEY is required")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.environ.get("CHAT_MODEL", "deepseek-flash")
        self.max_tokens = max_tokens
        self._client = OpenAI(
            api_key=key,
            base_url=self.base_url,
            timeout=300.0,
            max_retries=1,
        )

    def _request(self, kwargs: dict) -> Any:
        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as error:
            # Some OpenAI-compatible deployments reject response_format while
            # still following an explicit JSON-only prompt.
            if "response_format" not in str(error).lower():
                raise
            kwargs.pop("response_format")
            return self._client.chat.completions.create(**kwargs)

    def complete_json(
        self, *, call_id: str, system_prompt: str, user_prompt: str
    ) -> StructuredLLMResult:
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": self.max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        response = self._request(kwargs)
        message = response.choices[0].message
        text = message.content or ""
        finish_reason = response.choices[0].finish_reason
        # Reasoning models spend the output budget on hidden reasoning first.
        # A long packet can exhaust a small budget before any JSON is emitted,
        # which used to force an immediate deterministic fallback.  Retry once
        # with a wider budget instead of silently giving up.
        if not text and finish_reason == "length" and self.max_tokens < self.RETRY_MAX_TOKENS:
            kwargs["max_tokens"] = min(self.max_tokens * 2, self.RETRY_MAX_TOKENS)
            response = self._request(kwargs)
            message = response.choices[0].message
            text = message.content or ""
            finish_reason = response.choices[0].finish_reason
        usage = getattr(response, "usage", None)
        record = LLMCallRecord(
            call_id=call_id,
            model=self.model,
            raw_text=text,
            prompt_hash=_prompt_hash(system_prompt, user_prompt),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            finish_reason=finish_reason,
        )
        try:
            payload = _extract_json(text)
        except (ValueError, json.JSONDecodeError) as error:
            reasoning_length = len(getattr(message, "reasoning_content", "") or "")
            raise StructuredLLMError(
                f"invalid final JSON; content_chars={len(text)}; "
                f"reasoning_chars={reasoning_length}; finish_reason={record.finish_reason}; {error}",
                record,
            ) from error
        return StructuredLLMResult(payload=payload, record=record)


class StaticCouncilClient:
    """Thread-safe response map used by offline tests and replay fixtures."""

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self._lock = threading.Lock()

    def complete_json(
        self, *, call_id: str, system_prompt: str, user_prompt: str
    ) -> StructuredLLMResult:
        with self._lock:
            if call_id not in self.responses:
                raise KeyError(f"No static response for {call_id}")
            payload = self.responses[call_id]
        raw = json.dumps(payload, ensure_ascii=False)
        return StructuredLLMResult(
            payload=payload,
            record=LLMCallRecord(
                call_id=call_id,
                model="static-test-client",
                raw_text=raw,
                prompt_hash=_prompt_hash(system_prompt, user_prompt),
                finish_reason="stop",
            ),
        )
