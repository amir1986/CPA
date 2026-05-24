"""CSV → narrative spans (one per row).

The orchestrator embeds these as searchable chunks; the LLM needs a
narrative form, not raw rows, so we flatten each row into a
``col1=v1 | col2=v2`` string keyed by the header.
"""

from __future__ import annotations

import csv
import io

from app.ingest_docs.extractors.pdf_text import ExtractedSpan


def extract_csv(body: bytes, *, encoding: str = "utf-8") -> list[ExtractedSpan]:
    text = body.decode(encoding, errors="replace")
    # Sniff the dialect; fall back to plain comma on failure.
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    spans: list[ExtractedSpan] = []
    # Include the header row so the LLM has column names available.
    spans.append(ExtractedSpan(anchor="header", text=" | ".join(header)))
    for idx, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        flat = " | ".join(
            f"{(header[i] if i < len(header) else f'col{i+1}').strip()}={cell.strip()}"
            for i, cell in enumerate(row)
            if cell.strip()
        )
        if flat:
            spans.append(ExtractedSpan(anchor=f"row={idx}", text=flat))
    return spans
