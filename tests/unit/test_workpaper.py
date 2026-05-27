"""Workpaper renderer tests — DRAFT banner present, substitution works, missing keys safe."""

from __future__ import annotations

from app.audit.workpapers.renderer import DRAFT_BANNER, render_template


def test_je_testing_template_renders_with_draft_banner() -> None:
    wp = render_template(
        "je_testing",
        inputs={
            "title": "JE Testing — 2024 Year-end",
            "engagement_name": "ACME Audit 2024",
            "engagement_id": "eng-1",
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "performance_materiality": "100000",
            "entry_count": "12345",
            "prepared_by": "alice@firm.com",
            "generated_at": "2025-01-15T10:00:00Z",
            "findings_table": "| Test | Hits |\n|---|---|\n| Benford | 7 |",
            "citations": "- AU-C 240",
        },
        references={"sample_ids": ["a", "b"]},
    )
    assert wp.title == "JE Testing — 2024 Year-end"
    assert DRAFT_BANNER.strip() in wp.body_md
    assert "JE Testing — 2024 Year-end" in wp.body_md
    assert "ACME Audit 2024" in wp.body_md
    assert wp.references == {"sample_ids": ["a", "b"]}


def test_missing_inputs_are_safe() -> None:
    wp = render_template(
        "je_testing",
        inputs={"title": "minimal", "generated_at": "now"},
    )
    # safe_substitute leaves unknown placeholders as empty after our str-coercion → "" substituted.
    # The template renders without raising.
    assert "DRAFT" in wp.body_md
