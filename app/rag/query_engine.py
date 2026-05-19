"""Cited Q&A engine — retrieve, prompt, validate citations, refuse if grounded."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.domain.models import Citation, RetrievedChunk
from app.embeddings import get_embedder
from app.llm.client import LLMClient, get_llm
from app.rag.citation import validate_citations
from app.rag.lang import detect_language
from app.rag.prompts import REFUSAL_EN, REFUSAL_HE, SYSTEM_EN, SYSTEM_HE, build_user_prompt
from app.rag.vector_store import CPA_KNOWLEDGE, VectorStore, get_vector_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryAnswer:
    answer: str
    citations: list[Citation]
    refused: bool
    language: str
    retrieved: list[RetrievedChunk]


async def answer_question(
    question: str,
    *,
    jurisdictions: list[str] | None = None,
    corpus_types: list[str] | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    store: VectorStore | None = None,
    llm: LLMClient | None = None,
) -> QueryAnswer:
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    min_score = min_score or settings.retrieval_min_score
    language = detect_language(question)

    store = store or get_vector_store()
    embedder = get_embedder()
    llm = llm or get_llm()

    filters: dict[str, Any] = {}
    if jurisdictions:
        filters["jurisdiction"] = jurisdictions
    if corpus_types:
        filters["corpus_type"] = corpus_types
    # Strict language filter for HE per the plan; for EN we leave it open so
    # mixed-corpus queries still surface useful results.
    if language == "he" and settings.retrieval_lang_strict_he:
        filters["language"] = ["he"]

    qvec = embedder.embed_query(question)
    retrieved = await store.search(
        CPA_KNOWLEDGE,
        query_embedding=qvec,
        query_text=question,
        top_k=top_k,
        filters=filters,
    )

    if not retrieved or retrieved[0].score < min_score:
        return QueryAnswer(
            answer=REFUSAL_HE if language == "he" else REFUSAL_EN,
            citations=[],
            refused=True,
            language=language,
            retrieved=retrieved,
        )

    sources_text = [rc.chunk.text for rc in retrieved]
    user_prompt = build_user_prompt(question, sources_text)
    system_prompt = SYSTEM_HE if language == "he" else SYSTEM_EN

    response = await llm.complete(user_prompt, system=system_prompt)
    parsed = _parse_json(response.text)
    answer_text = str(parsed.get("answer", "")).strip()
    raw_citations = parsed.get("citations") or []

    validated = validate_citations(raw_citations, retrieved)
    if not answer_text or not validated.kept:
        if validated.dropped_reasons:
            logger.info("citations dropped: %s", validated.dropped_reasons)
        return QueryAnswer(
            answer=REFUSAL_HE if language == "he" else REFUSAL_EN,
            citations=[],
            refused=True,
            language=language,
            retrieved=retrieved,
        )

    return QueryAnswer(
        answer=answer_text,
        citations=list(validated.kept),
        refused=False,
        language=language,
        retrieved=retrieved,
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # Allow ```json ... ``` fences.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json\n"):
            text = text[5:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object substring.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}
