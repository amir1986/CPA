"""Source chunker.

Splits a normalized document into ~target_words chunks, breaking on paragraph
or sentence boundaries when possible. Returns objects with deterministic
content hashes so re-indexing produces the same vector IDs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

DEFAULT_TARGET_WORDS = 320
DEFAULT_OVERLAP_WORDS = 50


_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?׃])\s+")


@dataclass(frozen=True)
class TextChunk:
    text: str
    sha1: str
    word_count: int
    seq: int


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _split_words(text: str) -> list[str]:
    return text.split()


def chunk_text(
    text: str,
    *,
    target_words: int = DEFAULT_TARGET_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> list[TextChunk]:
    """Return ordered text chunks.

    Strategy:
    1. Split by paragraph; if a paragraph is short, accumulate into a buffer.
    2. When the buffer reaches ``target_words``, emit it and slide forward
       with ``overlap_words`` of overlap.
    3. If any paragraph alone exceeds ``target_words``, sentence-split it.
    """
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]

    units: list[str] = []
    for p in paragraphs:
        wc = len(_split_words(p))
        if wc <= target_words:
            units.append(p)
        else:
            sentences = [s.strip() for s in _SENTENCE_SPLIT.split(p) if s.strip()]
            if not sentences:
                units.append(p)
                continue
            buf: list[str] = []
            buf_wc = 0
            for s in sentences:
                swc = len(_split_words(s))
                if buf and buf_wc + swc > target_words:
                    units.append(" ".join(buf))
                    buf = [s]
                    buf_wc = swc
                else:
                    buf.append(s)
                    buf_wc += swc
            if buf:
                units.append(" ".join(buf))

    chunks: list[TextChunk] = []
    buf: list[str] = []
    buf_wc = 0
    seq = 0
    for u in units:
        uwc = len(_split_words(u))
        if buf and buf_wc + uwc > target_words:
            joined = "\n\n".join(buf)
            chunks.append(TextChunk(text=joined, sha1=_sha1(joined), word_count=buf_wc, seq=seq))
            seq += 1
            # Slide window: keep the tail words.
            tail_words = _split_words(joined)[-overlap_words:]
            buf = [" ".join(tail_words)] if tail_words else []
            buf_wc = len(tail_words)
        buf.append(u)
        buf_wc += uwc

    if buf:
        joined = "\n\n".join(buf)
        chunks.append(TextChunk(text=joined, sha1=_sha1(joined), word_count=buf_wc, seq=seq))
    return chunks
