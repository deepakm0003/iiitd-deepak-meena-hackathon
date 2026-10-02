"""Give SEC filings a real lead: the opening of the press release (EX-99.1), or of the main document.

Filing titles are templated ("X files 8-K: Item 2.02 Results of Operations"), so sentiment and embeddings
computed on the title alone carry no information. The lead is built from the filing text with the cover
page and item headings stripped (the item is already used as the event label, and must not leak into text
models).
"""

import re

from tripwire.ingestion.normalize import make_lead
from tripwire.models import Document
from tripwire.nlp.text import strip_filing_leakage

_BOILERPLATE = re.compile(
    r"^(exhibit\s+99\.?\d*|press release|news release|for immediate release|contacts?:.*|media:.*|investors?:.*)\s*",
    re.IGNORECASE,
)


_CONTACT = re.compile(r"@\w|\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b|\bcontacts?\b", re.IGNORECASE)


def filing_lead(main_text: str, exhibit_text: str, max_chars: int = 500) -> str:
    body = strip_filing_leakage(exhibit_text or main_text)
    lines = [ln.strip() for ln in body.splitlines()
             if len(ln.strip()) > 40 and not _CONTACT.search(ln)]  # skip headers, labels and contact blocks
    text = " ".join(_BOILERPLATE.sub("", ln) for ln in lines[:6])
    return make_lead(text, max_sentences=2, max_chars=max_chars)


def with_filing_leads(store, docs: list[Document]) -> list[Document]:
    out = []
    for doc in docs:
        if doc.source == "edgar" and not doc.lead and (accession := doc.hints.get("accession")):
            text = store.get_filing_text(accession)
            if text and text.status == "ok":
                doc = doc.model_copy(update={"lead": filing_lead(text.main_text, text.exhibit_text)})
        out.append(doc)
    return out
