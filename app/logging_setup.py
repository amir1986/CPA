"""Structured logging with OTEL trace correlation.

Configures structlog to emit JSON in production and a colored
key-value renderer in dev. Each record carries the current span's
trace_id + span_id when one is active so a log line can be
followed back to its trace in Tempo / Jaeger / OTel-LGTM.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog
from opentelemetry import trace


def _add_trace_context(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Stdlib root logger writes to stdout so containers see the records.
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stdout,
    )

    json_mode = os.environ.get("CPA_LOG_FORMAT", "json").lower() == "json"
    renderer: Any = (
        structlog.processors.JSONRenderer() if json_mode else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )
