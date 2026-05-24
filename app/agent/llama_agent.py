"""LlamaIndex-backed agent.

Builds a ``ReActAgent`` from our engagement-bound tools and our
LlamaIndex-wrapped LLM. We pull the reasoning trace from the agent's
``chat_history`` so it persists to ``agent_runs`` in exactly the same
shape as the simple backend.

Selection is via the ``CPA_AGENT_BACKEND`` env var:
- ``llamaindex`` (default in prod) → this module
- ``simple``  → ``app/agent/agent.py``'s hand-rolled JSON loop, kept for
  unit tests so they don't depend on LlamaIndex's optional deps.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.agent.agent import (  # re-used data shapes
    AgentResult,
    ToolCallEvent,
)
from app.agent.agent import (
    run_agent as run_simple_agent,
)
from app.agent.tools import Tool
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)


def _backend() -> str:
    return os.environ.get("CPA_AGENT_BACKEND", "llamaindex").lower()


async def run_agent(
    question: str,
    *,
    tools: list[Tool],
    llm: LLMClient,
    max_steps: int = 6,
) -> AgentResult:
    """Dispatch to LlamaIndex or to the simple loop."""
    if _backend() == "simple":
        return await run_simple_agent(question, tools=tools, llm=llm, max_steps=max_steps)

    try:
        return await _run_llamaindex(question, tools=tools, llm=llm, max_steps=max_steps)
    except Exception:
        logger.exception("LlamaIndex agent failed; falling back to simple loop")
        return await run_simple_agent(question, tools=tools, llm=llm, max_steps=max_steps)


async def _run_llamaindex(
    question: str,
    *,
    tools: list[Tool],
    llm: LLMClient,
    max_steps: int,
) -> AgentResult:
    from llama_index.core.agent import ReActAgent
    from llama_index.core.tools import FunctionTool

    from app.llm.llama_index_llm import OllamaCloudLlamaIndexLLM

    li_llm = OllamaCloudLlamaIndexLLM(client=llm)

    captured: list[ToolCallEvent] = []

    def _make_li_tool(tool: Tool) -> FunctionTool:
        async def _bridge(**kwargs: Any) -> str:
            try:
                result = await tool.fn(kwargs)
                captured.append(ToolCallEvent(tool=tool.name, arguments=dict(kwargs), result=result))
                return json.dumps(result)
            except Exception as exc:
                captured.append(ToolCallEvent(tool=tool.name, arguments=dict(kwargs), error=str(exc)))
                return json.dumps({"error": str(exc)})

        return FunctionTool.from_defaults(
            async_fn=_bridge,
            name=tool.name,
            description=tool.description,
        )

    li_tools = [_make_li_tool(t) for t in tools]

    agent = ReActAgent.from_tools(
        tools=li_tools,
        llm=li_llm,
        verbose=False,
        max_iterations=max_steps,
    )

    response = await agent.achat(question)
    final = str(response.response) if response and getattr(response, "response", None) else ""

    # Increment the agent-tool counter for each captured call.
    try:
        from app.telemetry import AGENT_TOOL_CALLS

        for ev in captured:
            AGENT_TOOL_CALLS.labels(tool=ev.tool).inc()
    except Exception:
        pass

    return AgentResult(final_answer=final, citations=[], tool_calls=captured)
