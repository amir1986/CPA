"""Seed a dev firm + admin user. Idempotent."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import select

from app.api.security import hash_password
from app.db.models.auth_models import Firm, User, UserRole
from app.db.session import get_sessionmaker

DEV_EMAIL = os.environ.get("CPA_SEED_EMAIL", "dev@cpa.local")
DEV_PASSWORD = os.environ.get("CPA_SEED_PASSWORD", "devpassword1234")
DEV_FIRM = os.environ.get("CPA_SEED_FIRM", "Dev Firm")


async def main() -> None:
    factory = get_sessionmaker()
    async with factory() as s:
        user = await s.scalar(select(User).where(User.email == DEV_EMAIL))
        if user is not None:
            print(f"already exists: {DEV_EMAIL}")
            return
        firm = await s.scalar(select(Firm).where(Firm.name == DEV_FIRM))
        if firm is None:
            firm = Firm(name=DEV_FIRM)
            s.add(firm)
            await s.flush()
        s.add(
            User(
                firm_id=firm.id,
                email=DEV_EMAIL,
                password_hash=hash_password(DEV_PASSWORD),
                role=UserRole.admin,
                name="Dev Admin",
                email_verified_at=datetime.now(tz=UTC),
            )
        )
        await s.commit()
        print(f"seeded dev firm + user: {DEV_EMAIL} / {DEV_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
