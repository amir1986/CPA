"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import (
    analyze,
    audit_routes,
    auth,
    clients,
    engagements,
    files,
    health,
    query,
    sources,
)
from app.config import get_settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(clients.router)
    app.include_router(engagements.router)
    app.include_router(files.router)
    app.include_router(query.router)
    app.include_router(sources.router)
    app.include_router(analyze.router)
    app.include_router(audit_routes.router)

    return app


app = create_app()
