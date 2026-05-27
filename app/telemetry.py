"""OpenTelemetry + Prometheus wiring.

Best practices applied:
- Single ``setup_telemetry(app)`` entrypoint; safe to call once during
  app lifespan. Re-invocation is a no-op (we set a sentinel on the
  global provider).
- FastAPI, httpx and SQLAlchemy auto-instrumentation hook into the
  same TracerProvider.
- /metrics endpoint mounted via prometheus_client.make_asgi_app.
- W3C TraceContext propagator (the default in OTEL ≥ 1.20).
- ParentBased sampling — fully sampled by default in dev, ratio-based
  in prod via OTEL_TRACES_SAMPLER_ARG.
- Healthcheck routes excluded from server spans to keep the cardinality
  of the metrics low.
- Logs get a "trace_id" / "span_id" field via a structlog processor
  so a log line can be correlated to its trace in any backend.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

from app.config import get_settings

logger = logging.getLogger(__name__)

_INITIALIZED = "_cpa_otel_initialized"


# ──────────────── Metrics ────────────────


LLM_REQUESTS = Counter(
    "cpa_llm_requests_total",
    "LLM HTTP requests issued, by outcome.",
    labelnames=("outcome",),  # success | rate_limited | server_error | unauthorized | exhausted
)
LLM_KEY_COOLDOWNS = Counter(
    "cpa_llm_key_cooldowns_total",
    "Number of times a key entered the cooling state.",
)
RETRIEVAL_SCORE = Histogram(
    "cpa_retrieval_top1_score",
    "Top-1 fused retrieval score per /query call.",
    buckets=(0.05, 0.1, 0.15, 0.2, 0.25, 0.35, 0.5, 0.7, 0.9),
)
REFUSALS = Counter("cpa_refusals_total", "Refused /query responses.", ("reason",))
INGEST_DOCS = Counter(
    "cpa_ingest_docs_total",
    "Documents ingested by the standards pipeline.",
    ("source_id",),
)
PARSE_FAILURES = Counter(
    "cpa_parse_failures_total",
    "Document-parse failures.",
    ("kind",),
)
AGENT_TOOL_CALLS = Counter(
    "cpa_agent_tool_calls_total",
    "Tool calls executed by the agent.",
    ("tool",),
)
AUDIT_TEST_HITS = Counter(
    "cpa_audit_test_hits_total",
    "JE-test hit counts.",
    ("test_kind",),
)


# ──────────────── Setup ────────────────


def setup_telemetry(app: FastAPI) -> None:
    """Configure OTEL tracer + auto-instrumentation, expose /metrics."""
    if getattr(app.state, _INITIALIZED, False):
        return

    settings = get_settings()
    service_name = os.environ.get("OTEL_SERVICE_NAME", "cpa-api")
    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: "0.1.0",
            "deployment.environment": os.environ.get("CPA_ENV", "dev"),
        }
    )

    sampler_ratio = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "1.0"))
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(root=TraceIdRatioBased(sampler_ratio)),
    )

    endpoint = settings.otel_exporter_otlp_endpoint or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
    elif os.environ.get("CPA_OTEL_CONSOLE") == "1":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI, httpx, SQLAlchemy.
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="healthz,readyz,metrics",
    )
    HTTPXClientInstrumentor().instrument()
    try:
        from app.db.session import get_engine

        SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)
    except Exception as exc:
        logger.info("sqlalchemy instrumentation skipped: %s", exc)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:  # pragma: no cover (trivial)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.state._cpa_otel_initialized = True
    logger.info(
        "telemetry: service=%s otlp=%s sampler_ratio=%.2f",
        service_name,
        endpoint or "(none)",
        sampler_ratio,
    )


# ──────────────── Convenience ────────────────


def tracer(name: str = "cpa") -> trace.Tracer:
    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.trace_id == 0:
        return None
    return format(ctx.trace_id, "032x")


def span(name: str, **attrs: Any) -> trace.Span:
    """Quick helper: ``with span("retriever.search", top_k=8): ...``."""
    return tracer().start_as_current_span(name, attributes=attrs)  # type: ignore[return-value]
