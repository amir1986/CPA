"""End-to-end agent loop test using FakeLLM + FakeTools."""

from __future__ import annotations

import json

import pytest

from app.agent.agent import run_agent
from app.agent.tools import Tool
from app.llm.client import FakeLLM


@pytest.mark.asyncio
async def test_agent_calls_tool_then_returns_final() -> None:
    calls: list[tuple[str, dict]] = []

    async def echo(args: dict) -> dict:
        calls.append(("echo", args))
        return {"echoed": args.get("value")}

    tools = [Tool(name="echo", description="echo back", parameters={"value": "any"}, fn=echo)]

    fake = FakeLLM()
    # The agent loop reads the FakeLLM response twice — once for the tool
    # call, once for the final answer. FakeLLM returns the same response
    # each call, so we encode a small state machine: first ask sets a
    # marker in the prompt, but FakeLLM ignores prompt — to drive the
    # loop we override `set_response` between calls via a counter.
    responses = iter([
        json.dumps({"tool": "echo", "arguments": {"value": "hello"}}),
        json.dumps({"final": "Got it.", "citations": []}),
    ])

    async def fake_complete(prompt, *, system=None):
        from app.llm.client import LLMResponse
        return LLMResponse(text=next(responses), usage={"prompt_tokens": 0, "completion_tokens": 0})

    fake.complete = fake_complete  # type: ignore[assignment]

    result = await run_agent("test question", tools=tools, llm=fake, max_steps=4)

    assert result.final_answer == "Got it."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool == "echo"
    assert result.tool_calls[0].result == {"echoed": "hello"}
    assert calls == [("echo", {"value": "hello"})]


@pytest.mark.asyncio
async def test_agent_returns_unknown_tool_to_history_and_keeps_going() -> None:
    async def tool_a(args: dict) -> dict:
        return {"ok": True}

    tools = [Tool(name="a", description="", parameters={}, fn=tool_a)]
    fake = FakeLLM()
    responses = iter([
        json.dumps({"tool": "nope", "arguments": {}}),
        json.dumps({"final": "fallback", "citations": []}),
    ])

    async def fake_complete(prompt, *, system=None):
        from app.llm.client import LLMResponse
        return LLMResponse(text=next(responses), usage={"prompt_tokens": 0, "completion_tokens": 0})

    fake.complete = fake_complete  # type: ignore[assignment]
    result = await run_agent("q", tools=tools, llm=fake, max_steps=4)
    assert result.final_answer == "fallback"


@pytest.mark.asyncio
async def test_agent_runs_out_of_steps() -> None:
    async def loop_tool(args: dict) -> dict:
        return {"keep_going": True}

    tools = [Tool(name="loop", description="", parameters={}, fn=loop_tool)]
    fake = FakeLLM()
    # Force the agent to keep calling the same tool forever.
    fake.set_response(json.dumps({"tool": "loop", "arguments": {}}))
    result = await run_agent("q", tools=tools, llm=fake, max_steps=3)
    assert "ran out of steps" in result.final_answer
    assert len(result.tool_calls) == 3
