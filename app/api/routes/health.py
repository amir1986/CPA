"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe — always 200 if process is up.")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe — true only if deps are reachable.")
async def readyz(response: Response) -> dict[str, object]:
    """Stub readiness check.

    Phase 1 only verifies that the rotator has at least one configured key.
    Later phases will also probe Postgres, Qdrant, and S3.
    """
    settings = get_settings()
    keys = settings.resolved_api_keys()
    ready = len(keys) > 0
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "ready": ready,
        "checks": {
            "ollama_keys": {"ok": len(keys) > 0, "count": len(keys)},
        },
    }
