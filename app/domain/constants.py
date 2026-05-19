"""Enumerations used across the RAG + ingest + agent layers."""

from __future__ import annotations

JURISDICTIONS = ("US", "IFRS", "IL")
CORPUS_TYPES = ("accounting", "auditing", "tax")
LANGUAGES = ("en", "he")

AUDIT_AREAS = (
    "revenue",
    "cogs",
    "payroll",
    "cash",
    "ar",
    "inventory",
    "ppe",
    "intangibles",
    "leases",
    "tax",
    "equity",
    "controls",
)
