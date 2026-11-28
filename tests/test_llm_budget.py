from __future__ import annotations

import unittest
from types import SimpleNamespace

from aster_council.llm import DeepSeekCouncilClient


def _response(content: str, finish_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, reasoning_content="hidden reasoning"),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


class FakeCompletions:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.responses.pop(0)


class LLMBudgetRetryTest(unittest.TestCase):
    def _client(self, completions: FakeCompletions) -> DeepSeekCouncilClient:
        client = DeepSeekCouncilClient(api_key="test-key", max_tokens=20000)
        client._client = SimpleNamespace(  # type: ignore[assignment]
            chat=SimpleNamespace(completions=completions)
        )
        return client

    def test_retries_with_wider_budget_when_reasoning_exhausts_output(self) -> None:
        fake = FakeCompletions([_response("", "length"), _response('{"ok": true}', "stop")])
        result = self._client(fake).complete_json(
            call_id="reviewer", system_prompt="system", user_prompt="user"
        )

        self.assertEqual(result.payload, {"ok": True})
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0]["max_tokens"], 20000)
        self.assertEqual(fake.calls[1]["max_tokens"], 32000)

    def test_does_not_retry_when_content_is_present(self) -> None:
        fake = FakeCompletions([_response('{"ok": true}', "stop")])
        result = self._client(fake).complete_json(
            call_id="reviewer", system_prompt="system", user_prompt="user"
        )

        self.assertEqual(result.payload, {"ok": True})
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
