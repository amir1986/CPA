"""Minimal tool-calling agent.

We don't pull LlamaIndex's FunctionAgent for v1 — instead, the LLM emits
JSON instructions in the form
``{"tool": "...", "arguments": {...}}`` or ``{"final": "...", "citations": [...]}``,
which we execute in a small loop. This keeps the dependency footprint small
and the loop fully deterministic when paired with the FakeLLM.

Trace persistence is the caller's job — the agent yields each tool call +
result so the router can stream them and write to ``agent_runs`` at the end.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from app.agent.tools import Tool
from app.llm.client import LLMClient
from app.rag.prompts import SYSTEM_EN


logger = logging.getLogger(__name__)


AGENT_SYSTEM = (
    SYSTEM_EN
    + "\n\nYou have tools available. To call a tool, return STRICT JSON:\n"
    + '{"tool": "tool_name", "arguments": {...}}\n'
    + "When you have enough information, return your final answer as:\n"
    + '{"final": "...", "citations": [...]}\n'
    + "Never call the same tool with identical arguments twice in a row."
)


@dataclass
class ToolCallEvent:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class AgentResult:
    final_answer: str
    citations: list[dict[str, Any]]
    tool_calls: list[ToolCallEvent] = field(default_factory=list)


def _tools_manifest(tools: list[Tool]) -> str:
    return "\n".join(
        f"- {t.name}: {t.description} (params: {json.dumps(t.parameters)})"
        for t in tools
    )


async def run_agent(
    question: str,
    *,
    tools: list[Tool],
    llm: LLMClient,
    max_steps: int = 6,
) -> AgentResult:
    """Run a tool-calling loop until ``final`` or ``max_steps`` is reached."""
    tools_by_name = {t.name: t for t in tools}
    history: list[dict[str, Any]] = []

    for step in range(max_steps):
        prompt = (
            f"QUESTION: {question}\n\n"
            f"AVAILABLE TOOLS:\n{_tools_manifest(tools)}\n\n"
            f"HISTORY (tool_call → result):\n{json.dumps(history, indent=2)[:4000]}\n\n"
            "Respond with a single JSON object. No prose."
        )
        response = await llm.complete(prompt, system=AGENT_SYSTEM)
        parsed = _parse_json(response.text)

        if "final" in parsed:
            return AgentResult(
                final_answer=str(parsed.get("final", "")),
                citations=list(parsed.get("citations") or []),
                tool_calls=[
                    ToolCallEvent(tool=h["tool"], arguments=h["arguments"], result=h.get("result"))
                    for h in history
                ],
            )

        tool_name = parsed.get("tool")
        if tool_name not in tools_by_name:
            history.append({"tool": tool_name or "?", "arguments": parsed.get("arguments", {}), "error": "unknown tool"})
            continue

        args = parsed.get("arguments") or {}
        try:
            result = await tools_by_name[tool_name].fn(args)
        except Exception as exc:  # noqa: BLE001 — surfacing to history is intentional
            logger.exception("tool %s raised", tool_name)
            history.append({"tool": tool_name, "arguments": args, "error": str(exc)})
            continue
        history.append({"tool": tool_name, "arguments": args, "result": result})

    return AgentResult(
        final_answer="(agent ran out of steps without a final answer)",
        citations=[],
        tool_calls=[
            ToolCallEvent(tool=h["tool"], arguments=h["arguments"], result=h.get("result"))
            for h in history
        ],
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json\n"):
            text = text[5:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}
