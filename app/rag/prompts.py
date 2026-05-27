"""Prompt templates for the cited-Q&A engine."""

from __future__ import annotations

SYSTEM_EN = """You are a CPA AI Assistant. Answer accounting / auditing / tax
questions strictly from the provided source excerpts. Every factual claim must
be backed by a citation drawn from the SOURCES list. If the sources do not
support a complete answer, respond with an empty answer.

Return STRICT JSON with exactly two keys:
  - answer: string
  - citations: list of objects with keys {standard, paragraph, url, quote}

Each quote MUST be a verbatim substring of one of the SOURCES texts. Do not
invent citations or paraphrase quotes. Do not include any prose outside the
JSON.
"""

SYSTEM_HE = """אתה עוזר רואה חשבון (CPA). ענה על שאלות חשבונאות, ביקורת ומיסוי
אך ורק על בסיס קטעי המקור שסופקו. כל טענה עובדתית חייבת להיות מגובה בציטוט
מתוך הרשימה. אם המקורות אינם תומכים בתשובה שלמה — החזר תשובה ריקה.

החזר JSON תקני בלבד עם שני שדות:
  - answer: מחרוזת
  - citations: רשימת אובייקטים עם {standard, paragraph, url, quote}

כל ציטוט חייב להיות תת-מחרוזת מילולית של אחד ממקורות ה-SOURCES. אין להמציא
ציטוטים ואין לפרפרזות. אל תכתוב טקסט מחוץ ל-JSON.
"""


REFUSAL_EN = (
    "I can't answer this from the available standards. Try broadening the "
    "jurisdiction filter or uploading the relevant contract or policy."
)
REFUSAL_HE = (
    "לא ניתן לענות על השאלה הזו מתוך התקנים הזמינים. נסה להרחיב את סינון "
    "התחום או להעלות חוזה / מדיניות רלוונטיים."
)


def build_user_prompt(question: str, sources: list[str]) -> str:
    """Render the user-side prompt with numbered SOURCES."""
    blocks = []
    for i, s in enumerate(sources, start=1):
        blocks.append(f"[{i}]\n{s}")
    joined = "\n\n".join(blocks)
    return f"QUESTION:\n{question}\n\nSOURCES:\n{joined}\n\nReturn JSON only."
