"""/engagements/{eid}/agent — run the tool-calling agent, persist the trace."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llama_agent import run_agent
from app.agent.tools import build_tools
from app.api.auth import RequestPrincipal, current_principal
from app.api.errors import ApiError
from app.api.routes.engagements import ensure_in_firm
from app.api.schemas.agent import AgentIn, AgentRunOut, ToolCallOut
from app.db.models.observability import AgentRun
from app.db.session import get_session
from app.llm.client import get_llm

router = APIRouter(prefix="/engagements/{engagement_id}/agent", tags=["agent"])


@router.post("", response_model=AgentRunOut)
async def run_agent_endpoint(
    engagement_id: uuid.UUID,
    payload: AgentIn,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    await ensure_in_firm(engagement_id, principal, session)
    tools = build_tools(engagement_id=engagement_id, session=session)
    result = await run_agent(
        payload.question,
        tools=tools,
        llm=get_llm(),
        max_steps=payload.max_steps,
    )
    row = AgentRun(
        engagement_id=engagement_id,
        user_id=principal.user_id if principal.user_id.int != 0 else None,
        request=payload.question,
        tool_calls=[
            {"tool": tc.tool, "arguments": tc.arguments, "result": tc.result, "error": tc.error}
            for tc in result.tool_calls
        ],
        final_answer=result.final_answer,
        citations=result.citations,
        created_at=datetime.now(tz=UTC),
    )
    session.add(row)
    await session.flush()
    return AgentRunOut(
        id=str(row.id),
        request=row.request,
        final_answer=row.final_answer,
        citations=row.citations,
        tool_calls=[ToolCallOut(**tc) for tc in row.tool_calls],
        created_at=row.created_at,
    )


@router.get("/runs", response_model=list[AgentRunOut])
async def list_runs(
    engagement_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
    limit: int = 25,
) -> list[AgentRunOut]:
    await ensure_in_firm(engagement_id, principal, session)
    rows = (
        await session.scalars(
            select(AgentRun)
            .where(AgentRun.engagement_id == engagement_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        AgentRunOut(
            id=str(r.id),
            request=r.request,
            final_answer=r.final_answer,
            citations=r.citations,
            tool_calls=[ToolCallOut(**tc) for tc in r.tool_calls],
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=AgentRunOut)
async def get_run(
    engagement_id: uuid.UUID,
    run_id: uuid.UUID,
    principal: RequestPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    await ensure_in_firm(engagement_id, principal, session)
    r = await session.get(AgentRun, run_id)
    if r is None or r.engagement_id != engagement_id:
        raise ApiError(status=404, code="not_found", detail="run not found")
    return AgentRunOut(
        id=str(r.id),
        request=r.request,
        final_answer=r.final_answer,
        citations=r.citations,
        tool_calls=[ToolCallOut(**tc) for tc in r.tool_calls],
        created_at=r.created_at,
    )
