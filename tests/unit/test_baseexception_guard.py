"""Tests for the ASGI BaseExceptionGuard middleware.

Background: `pyo3_runtime.PanicException` (raised by cryptography's Rust
bindings on hosts with broken `_cffi_backend` / native openssl) subclasses
`BaseException` directly, NOT `Exception`. FastAPI's
`@exception_handler(Exception)` doesn't catch it, so the panic escapes
to uvicorn, which returns a bare "Internal Server Error" 500 with no
JSON body. The UI's `body.detail ?? fallback` then renders the opaque
"הייצוא נכשל (500)" pill the user reported on Render.

The guard converts these to a real `application/problem+json` 500 so the
UI can read a `detail` out of it. Plain Exception is re-raised so
FastAPI's existing Exception handler still wins (this guard is ONLY
for the BaseException-but-not-Exception subset).
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_error_handlers


class _FakePanic(BaseException):
    """Stand-in for pyo3_runtime.PanicException — a direct BaseException
    subclass, NOT an Exception subclass."""


@pytest.fixture
def app_with_panic_route() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/panic")
    async def panic_route() -> dict:
        raise _FakePanic("simulated rust panic")

    @app.get("/boom")
    async def boom_route() -> dict:
        raise RuntimeError("ordinary exception")

    @app.get("/ok")
    async def ok_route() -> dict:
        return {"hello": "world"}

    return app


def test_baseexception_panic_becomes_problem_json_500(app_with_panic_route: FastAPI) -> None:
    """Without the guard, this request would return a bare
    'Internal Server Error' plain-text 500 (no JSON body) — the exact
    failure the user reported on Render."""
    with TestClient(app_with_panic_route, raise_server_exceptions=False) as client:
        res = client.get("/panic")

    assert res.status_code == 500
    assert "json" in res.headers.get("content-type", "")
    body = res.json()
    assert body["status"] == 500
    assert body["title"] == "internal_panic"
    assert "simulated rust panic" in body["detail"]


def test_plain_exception_still_handled_by_fastapi(app_with_panic_route: FastAPI) -> None:
    """The guard must not steal Exception-handling away from FastAPI's
    own registered handler — only BaseException-but-not-Exception
    falls through to it."""
    with TestClient(app_with_panic_route, raise_server_exceptions=False) as client:
        res = client.get("/boom")

    assert res.status_code == 500
    body = res.json()
    # FastAPI's _unhandled handler emits title="internal_error", not
    # "internal_panic" — confirms the guard re-raised and didn't steal.
    assert body["title"] == "internal_error"
    assert "ordinary exception" in body["detail"]


def test_successful_request_unaffected(app_with_panic_route: FastAPI) -> None:
    """Sanity check: requests that don't raise still flow through the
    middleware without modification."""
    with TestClient(app_with_panic_route) as client:
        res = client.get("/ok")
    assert res.status_code == 200
    assert res.json() == {"hello": "world"}


def test_baseexception_response_is_parseable_json(app_with_panic_route: FastAPI) -> None:
    """Reproduces the symptom the user reported: ExportMemoButton does
    ``await res.json().catch(() => ({}))`` and reads ``body.detail``.
    If the response isn't valid JSON, the user sees the i18n fallback
    "הייצוא נכשל (500)" pill. Confirm the guard's body is parseable."""
    with TestClient(app_with_panic_route, raise_server_exceptions=False) as client:
        res = client.get("/panic")

    parsed = json.loads(res.content)
    assert isinstance(parsed.get("detail"), str)
    assert len(parsed["detail"]) > 0
