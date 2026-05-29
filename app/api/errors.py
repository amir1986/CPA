"""Problem+json error envelope + handlers."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Application-level error mapped to RFC-7807 problem+json."""

    def __init__(
        self,
        *,
        status: int,
        code: str,
        detail: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra or {}


def _problem(status: int, code: str, detail: str, extra: dict[str, Any] | None = None) -> JSONResponse:
    body = {"type": f"about:blank/{code}", "title": code, "status": status, "detail": detail}
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


class BaseExceptionGuard:
    """Pure-ASGI middleware that catches BaseException-derived errors
    escaping FastAPI's `@exception_handler(Exception)` and converts them
    to a proper problem+json 500 the UI can parse.

    Why this exists: `pyo3_runtime.PanicException` (raised by
    cryptography's Rust bindings when the host's `_cffi_backend` /
    native openssl is broken — observed on Render's free-tier slim
    install) subclasses BaseException directly, NOT Exception. Without
    this middleware the panic propagates all the way to uvicorn, which
    returns a bare "Internal Server Error" plain-text 500 with no JSON
    body — ExportMemoButton's ``body.detail ?? fallback`` then renders
    the opaque "הייצוא נכשל (500)" pill the user reported. Same hazard
    applies to any future native dep that decides to panic instead of
    raising Exception.

    Implemented as pure ASGI (not `BaseHTTPMiddleware`) because that
    helper buffers the response body, which would break the SSE stream
    at /comparison/runs/{id}/stream.

    Process / task control signals (KeyboardInterrupt, SystemExit,
    asyncio.CancelledError, GeneratorExit) are re-raised so uvicorn
    shutdown and ASGI cancellation still work. Plain Exception is
    re-raised so FastAPI's registered handler still wins (this guard
    is ONLY for the BaseException-but-not-Exception subset).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking(message: dict) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            # Let FastAPI's @exception_handler(Exception) render this.
            raise
        except BaseException as exc:
            logger.exception("BaseExceptionGuard caught non-Exception: %r", exc)
            if response_started:
                # Headers already flushed — we can't change the status
                # code now. Best we can do is let the connection close
                # so the proxy sees a partial response and can decide
                # to retry. Re-raising would also work; just don't
                # try to send a fresh 500.
                return
            body = json.dumps(
                {
                    "type": "about:blank/internal_panic",
                    "title": "internal_panic",
                    "status": 500,
                    "detail": repr(exc),
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})


def register_error_handlers(app: FastAPI) -> None:
    # Outermost layer in the middleware stack so it wraps every
    # downstream middleware, dependency, and route body. ASGI middleware
    # added via `add_middleware` ends up OUTSIDE everything added later,
    # which is the position we want for a catch-all panic guard.
    app.add_middleware(BaseExceptionGuard)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _problem(exc.status, exc.code, exc.detail, exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(exc.status_code, _http_code(exc.status_code), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            422,
            "validation_failed",
            "Request validation failed.",
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception")
        return _problem(500, "internal_error", str(exc))


def _http_code(status: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "unprocessable",
        429: "rate_limited",
        503: "unavailable",
    }.get(status, f"http_{status}")
