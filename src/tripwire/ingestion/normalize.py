"""Raw document -> clean Document. Formatting only: no meaning is added or removed here.

Problems that make a record unusable (empty title, future timestamp, non-English) raise NormalizationError
and the record goes to the quarantine table instead of crashing the worker.
"""

import html
import re
from datetime import datetime, timedelta

from tripwire.ids import canonical_url
from tripwire.models import Document, RawDocument, utc_now

TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
MENTION = re.compile(r"(?<!\w)@[\w.\-]+")
URL = re.compile(r"https?://\S+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
HINT_KEYS = (
    "matched_tickers", "macro_orgs", "orgs", "themes", "tone", "locations",  # GDELT
    "related", "query_ticker", "publisher", "category",                       # Finnhub
    "cik", "ticker", "form", "items", "accession", "primary_document",       # EDGAR
    "tickers", "author",                                                      # Bluesky
    "feed", "tags", "source_name",                                            # RSS / GDELT
)
MAX_FUTURE = timedelta(minutes=10)


class NormalizationError(ValueError):
    pass


REPLACEMENT_CHAR = "\ufffd"  # what a feed sends when its own encoding broke (e.g. "Amazon\ufffds")


def clean_text(value: str) -> str:
    value = html.unescape(html.unescape(value or ""))  # some feeds double-escape (&amp;amp;)
    value = re.sub(r"(?<=\w)\ufffd(?=(s|t|re|ll|ve|d)\b)", "'", value)  # broken apostrophe in "X's", "don't"
    value = value.replace(REPLACEMENT_CHAR, " ")
    return SPACE.sub(" ", TAG.sub(" ", value)).strip()



def make_lead(text: str, max_sentences: int = 2, max_chars: int = 600) -> str:
    sentences = SENTENCE_END.split(text)
    lead = " ".join(sentences[:max_sentences]).strip()
    return lead if len(lead) <= max_chars else lead[: max_chars - 1].rsplit(" ", 1)[0] + "…"


def normalize(raw_id: int, raw: RawDocument, now: datetime | None = None) -> Document:
    now = now or utc_now()
    title = clean_text(raw.title)
    text = clean_text(raw.text)
    if raw.source_type == "social":  # drop @handles and links: noise for NLP, and other users' identifiers
        title = SPACE.sub(" ", URL.sub("", MENTION.sub("@user", title))).strip()
        text = SPACE.sub(" ", URL.sub("", MENTION.sub("@user", text))).strip()
    if not title:
        raise NormalizationError("empty title")
    if raw.published_at > now + MAX_FUTURE:
        raise NormalizationError(f"published_at {raw.published_at.isoformat()} is in the future")
    lang = str(raw.payload.get("lang") or "en").lower()[:8]
    if not lang.startswith("en"):
        raise NormalizationError(f"non-English ({lang})")
    lead = make_lead(text) if text else ""
    if lead.casefold() == title.casefold():
        lead = ""
    return Document(
        raw_id=raw_id,
        dedup_key=raw.dedup_key,
        source=raw.source,
        source_type=raw.source_type,
        title=title,
        lead=lead,
        lang="en",
        url=canonical_url(raw.url) if raw.url else None,
        published_at=raw.published_at,
        normalized_at=now,
        hints={k: raw.payload[k] for k in HINT_KEYS if k in raw.payload},
    )
