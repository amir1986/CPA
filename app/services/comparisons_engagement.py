"""Per-user hidden 'comparisons' engagement that backs the USGAAP <> IFRS tool.

The top-level tool isn't tied to a real engagement, but every existing file
upload and workpaper code path requires one. Rather than make engagement_id
nullable across the codebase (and risk multi-tenant regressions), each user
gets a dedicated invisible engagement on first use. It is filtered out of
every public engagements list. It is **per-user, not per-firm**: two users
in the same firm never share an S3 directory or row visibility.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.engagement import Client, Engagement, EngagementType

# Stable, recognizable names so a human poking at the DB can tell what these are.
HIDDEN_CLIENT_NAME = "__comparisons__"


def _hidden_engagement_name(user_id: uuid.UUID) -> str:
    return f"__comparisons__:{user_id}"


async def get_or_create_hidden_engagement(
    *,
    user_id: uuid.UUID,
    firm_id: uuid.UUID,
    session: AsyncSession,
) -> Engagement:
    """Return the user's hidden comparisons engagement, creating it if needed."""
    name = _hidden_engagement_name(user_id)

    # Lookup by (firm-scoped client) + name. Cheap because of the existing
    # ix_engagements_client_id index.
    existing = await session.scalar(
        select(Engagement)
        .join(Client, Client.id == Engagement.client_id)
        .where(Client.firm_id == firm_id)
        .where(Engagement.type == EngagementType.comparisons)
        .where(Engagement.name == name)
    )
    if existing is not None:
        return existing

    # One hidden client per firm — shared across the firm's users. Lookup or
    # create. The per-user uniqueness comes from the engagement name.
    client = await session.scalar(
        select(Client).where(Client.firm_id == firm_id).where(Client.name == HIDDEN_CLIENT_NAME)
    )
    if client is None:
        client = Client(firm_id=firm_id, name=HIDDEN_CLIENT_NAME)
        session.add(client)
        await session.flush()

    eng = Engagement(
        client_id=client.id,
        name=name,
        type=EngagementType.comparisons,
    )
    session.add(eng)
    await session.flush()
    return eng
