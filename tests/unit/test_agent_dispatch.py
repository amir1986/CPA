"""The agent route now goes through app.agent.llama_agent.run_agent.

When CPA_AGENT_BACKEND=simple is set, that wrapper short-circuits to the
hand-rolled loop — guaranteed to work in CI without LlamaIndex.
"""

from __future__ import annotations

import json

import pytest

from app.agent.llama_agent import run_agent
from app.agent.tools import Tool
from app.llm.client import FakeLLM, LLMResponse


@pytest.mark.asyncio
async def test_dispatch_uses_simple_loop_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPA_AGENT_BACKEND", "simple")

    async def echo(args: dict) -> dict:
        return {"got": args.get("value")}

    tools = [Tool(name="echo", description="echo", parameters={"value": "any"}, fn=echo)]

    fake = FakeLLM()
    responses = iter([
        json.dumps({"tool": "echo", "arguments": {"value": 42}}),
        json.dumps({"final": "done", "citations": []}),
    ])

    async def fake_complete(prompt: str, *, system: str | None = None) -> LLMResponse:
        return LLMResponse(text=next(responses), usage={"prompt_tokens": 0, "completion_tokens": 0})

    fake.complete = fake_complete  # type: ignore[assignment]

    result = await run_agent("q", tools=tools, llm=fake, max_steps=3)
    assert result.final_answer == "done"
    assert [tc.tool for tc in result.tool_calls] == ["echo"]
    assert result.tool_calls[0].result == {"got": 42}
