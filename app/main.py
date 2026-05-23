"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.logging_setup import configure_logging
from app.telemetry import setup_telemetry
from app.api.routes import (
    admin,
    agent_route,
    analyze,
    audit_routes,
    auth,
    clients,
    coa,
    engagements,
    files,
    gl,
    health,
    knowledge,
    query,
    sources,
    tweaks,
)
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info(
        "CPA api starting (model=%s, keys=%d)",
        settings.ollama_model,
        len(settings.resolved_api_keys()),
    )
    yield
    logging.getLogger(__name__).info("CPA api shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="CPA AI Assistant API",
        version="0.1.0",
        lifespan=lifespan,
    )

    settings = get_settings()

    # CORS — local dev hosts + any explicit `CPA_CORS_ORIGINS` (comma-separated)
    # + every *.vercel.app subdomain (the typical web host) via regex. The web
    # tier proxies all API calls server-side so the browser rarely hits the
    # api directly, but we keep CORS permissive to support direct curl and
    # other clients during diagnostics.
    import os

    cors_origins: list[str] = ["http://localhost:8080", "http://localhost:3000"]
    if extra := os.environ.get("CPA_CORS_ORIGINS"):
        cors_origins.extend(o.strip() for o in extra.split(",") if o.strip())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.onrender\.com",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    setup_telemetry(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(clients.router)
    app.include_router(engagements.router)
    app.include_router(files.router)
    app.include_router(query.router)
    app.include_router(sources.router)
    app.include_router(analyze.router)
    app.include_router(audit_routes.router)
    app.include_router(coa.router)
    app.include_router(gl.router)
    app.include_router(tweaks.router)
    app.include_router(admin.router)
    app.include_router(agent_route.router)
    app.include_router(knowledge.router)

    return app


app = create_app()
