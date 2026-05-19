"""Language detection — Hebrew vs English (other languages fall back to en).

We don't depend on a heavyweight detector; for the EN+HE corpus, a unicode
range count is sufficient and deterministic.
"""

from __future__ import annotations


def detect_language(text: str) -> str:
    if not text:
        return "en"
    hebrew = sum(1 for ch in text if "֐" <= ch <= "׿")
    latin = sum(1 for ch in text if "A" <= ch <= "Z" or "a" <= ch <= "z")
    return "he" if hebrew > latin else "en"
