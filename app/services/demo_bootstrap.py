"""Idempotently provision the shared demo user that every API request
falls back to after the login flow was removed.

Run once at api startup from app.main.lifespan. Safe to call repeatedly —
all inserts are guarded by SELECT-then-INSERT. Returns the demo user id
for logging.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.api.auth import DEMO_USER_EMAIL
from app.api.security import hash_password
from app.db.models.auth_models import Firm, User, UserRole
from app.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

DEMO_FIRM_NAME = "Demo Firm"
DEMO_USER_NAME = "Demo User"
# Used only if someone tries the legacy /auth/login form against this
# email — the password is never enforced for normal requests because the
# permissive resolver short-circuits to this user regardless of headers.
DEMO_USER_PASSWORD = "demo-skip-pass-1234"


async def ensure_demo_user_exists() -> uuid.UUID | None:
    """Create the demo firm + user if they don't already exist. Idempotent.

    Returns the user id on success; None if anything went wrong (logged).
    Failure here must NOT prevent api startup, so every error is caught
    and the api boots with no demo user — incoming requests will then 503
    with a clear 'demo user has not been provisioned' detail.
    """
    try:
        factory = get_sessionmaker()
        async with factory() as session:
            existing = (
                await session.execute(select(User).where(User.email == DEMO_USER_EMAIL))
            ).scalar_one_or_none()
            if existing is not None:
                # Backfill the locale default for a demo user provisioned
                # before Hebrew became the default. Only upgrades the stale
                # "en" that the old bootstrap wrote — a deliberate switch to
                # English via the toggle persists a different value path and
                # is left alone only if it's not the old default. (Single
                # shared demo user; the owner asked for Hebrew-by-default.)
                if existing.locale == "en":
                    existing.locale = "he"
                    await session.commit()
                    logger.info("demo user locale upgraded en→he: %s", existing.id)
                else:
                    logger.info("demo user already provisioned: %s", existing.id)
                return existing.id

            firm = (
                await session.execute(select(Firm).where(Firm.name == DEMO_FIRM_NAME))
            ).scalar_one_or_none()
            if firm is None:
                firm = Firm(name=DEMO_FIRM_NAME)
                session.add(firm)
                await session.flush()

            user = User(
                firm_id=firm.id,
                email=DEMO_USER_EMAIL,
                password_hash=hash_password(DEMO_USER_PASSWORD),
                role=UserRole.admin,
                name=DEMO_USER_NAME,
                locale="he",
            )
            session.add(user)
            await session.commit()
            logger.info("provisioned demo user: %s (firm=%s)", user.id, firm.id)
            return user.id
    except Exception as exc:
        logger.exception("ensure_demo_user_exists failed: %s", exc)
        return None
