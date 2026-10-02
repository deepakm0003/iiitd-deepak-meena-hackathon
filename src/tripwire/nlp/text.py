"""Small text utilities shared by the NLP stages."""

import re

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+")
# 8-K boilerplate and item headings. Removed before any classifier training or evaluation, because the item
# number IS the weak label: leaving 'Item 2.02 Results of Operations' in the text lets a model cheat.
_ITEM_HEADING = re.compile(r"\bItem\s+\d\.\d{2}\b[^\n.]{0,120}", re.IGNORECASE)
_COVER = re.compile(
    r"UNITED STATES\s+SECURITIES AND EXCHANGE COMMISSION.*?(?=\bItem\s+\d\.\d{2}\b|$)", re.IGNORECASE | re.DOTALL
)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def strip_filing_leakage(text: str) -> str:
    """Drop the 8-K cover page and every 'Item x.xx ...' heading, keeping the substantive text."""
    text = _COVER.sub(" ", text or "")
    text = _ITEM_HEADING.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text).strip()
