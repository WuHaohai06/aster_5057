"""Make one minimal QuantaAlpha chat call without printing credentials."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from quantaalpha.llm.client import APIBackend


def main() -> None:
    expected = "ASTER_DEEPSEEK_OK"
    backend = APIBackend()
    response = backend.build_messages_and_create_chat_completion(
        'Return only this JSON object: {"status":"ASTER_DEEPSEEK_OK"}',
        "You are a connectivity test. Follow the output format exactly.",
        max_tokens=64,
        temperature=0.0,
        reasoning_flag=True,
    )
    parsed = json.loads(response)
    if parsed.get("status") != expected:
        raise RuntimeError("The model responded, but failed the structured-output check")
    print(
        json.dumps(
            {
                "status": "ok",
                "provider_host": urlparse(os.environ["OPENAI_BASE_URL"]).netloc,
                "chat_model": os.environ["CHAT_MODEL"],
                "reasoning_model": os.environ["REASONING_MODEL"],
                "structured_response": expected,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
