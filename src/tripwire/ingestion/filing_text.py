"""Fetch the text of 8-K filings: the main document and, when present, the press-release exhibit (EX-99.1).

Most of an 8-K's substance sits in EX-99.1 (the press release); the main document often only says
"see Exhibit 99.1". Texts are stored verbatim (OBSERVED) in their own table. Anything that could leak the
label into a classifier (e.g. 'Item 2.02' headings) is stripped later, at training/evaluation time.
"""

import html
import re
from datetime import UTC, datetime

from tripwire.ingestion.http import HttpClient, HttpError
from tripwire.models import FilingText

INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/index.json"
FILE = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"
EX991 = re.compile(r"ex[-_]?99[-_.]?0?1(?!\d)|ex[-_]?99(?!\d)", re.IGNORECASE)
TEXT_SUFFIXES = (".htm", ".html", ".txt")
MAX_MAIN, MAX_EXHIBIT = 20_000, 30_000

_HIDDEN = re.compile(r"<ix:header>.*?</ix:header>|<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BREAKS = re.compile(r"<\s*(br|/p|/div|/tr|/li|/h\d)[^>]*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(markup: str) -> str:
    """Readable text from EDGAR HTML/iXBRL: drop hidden XBRL headers, scripts and tags; keep paragraph breaks."""
    markup = _HIDDEN.sub(" ", markup)
    markup = _BREAKS.sub("\n", markup)
    text = html.unescape(_TAGS.sub(" ", markup)).replace("\xa0", " ")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def pick_exhibit(names: list[str]) -> str | None:
    candidates = [n for n in names if n.lower().endswith(TEXT_SUFFIXES) and EX991.search(n)]
    # Prefer an explicit 99.1 over a bare 99, then the shortest name.
    candidates.sort(key=lambda n: (not re.search(r"99[-_.]?0?1(?!\d)", n), len(n)))
    return candidates[0] if candidates else None


def fetch_filing_text(http: HttpClient, cik: int, accession: str, primary_document: str | None) -> FilingText:
    folder = accession.replace("-", "")
    row = FilingText(accession=accession, cik=cik, fetched_at=datetime.now(UTC))
    try:
        names = [item["name"] for item in http.get(INDEX.format(cik=cik, folder=folder)).json()["directory"]["item"]]
        main = primary_document or next((n for n in names if n.lower().endswith((".htm", ".html"))), None)
        if main:
            row.main_text = html_to_text(http.get(FILE.format(cik=cik, folder=folder, name=main)).text)[:MAX_MAIN]
        exhibit = pick_exhibit([n for n in names if n != main])
        if exhibit:
            row.exhibit_name = exhibit
            row.exhibit_text = html_to_text(http.get(FILE.format(cik=cik, folder=folder, name=exhibit)).text)[
                :MAX_EXHIBIT
            ]
    except (HttpError, KeyError, ValueError) as exc:
        row.status, row.error = "error", f"{type(exc).__name__}: {exc}"[:300]
    return row
