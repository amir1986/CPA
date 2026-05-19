"""Unit tests for the source chunker."""

from __future__ import annotations

from app.rag.chunker import chunk_text


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_fits_in_one_chunk() -> None:
    text = "Revenue is recognized when control transfers."
    chunks = chunk_text(text, target_words=200)
    assert len(chunks) == 1
    assert chunks[0].text == text


def test_long_text_splits_with_overlap() -> None:
    paragraphs = []
    for i in range(20):
        paragraphs.append(f"Paragraph {i}: " + ("word " * 40).strip())
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, target_words=200, overlap_words=30)
    assert len(chunks) > 1
    # Sequence numbers ascend.
    assert [c.seq for c in chunks] == list(range(len(chunks)))


def test_oversized_paragraph_is_sentence_split() -> None:
    sentences = ". ".join(f"Sentence number {i}" for i in range(80)) + "."
    chunks = chunk_text(sentences, target_words=50)
    assert len(chunks) > 1


def test_chunks_are_deterministic() -> None:
    text = "\n\n".join(f"P{i} " + ("foo " * 30) for i in range(10))
    a = chunk_text(text)
    b = chunk_text(text)
    assert [c.sha1 for c in a] == [c.sha1 for c in b]
