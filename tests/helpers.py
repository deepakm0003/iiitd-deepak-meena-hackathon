"""Test helpers: an HTTP client backed by canned responses (no network in tests)."""

from collections.abc import Callable

import httpx

from tripwire.ingestion.http import HttpClient
from tripwire.universe import Company


def fake_http(handler: Callable[[httpx.Request], httpx.Response], sleeps: list | None = None) -> HttpClient:
    record = sleeps if sleeps is not None else []
    return HttpClient("Tripwire tests test@example.com", transport=httpx.MockTransport(handler), sleep=record.append)


COMPANIES = [
    Company(ticker="JPM", sector="Financials", aliases=("JPMorgan Chase", "JPMorgan"), cik=19617,
            sec_name="JPMORGAN CHASE & CO"),
    Company(ticker="UPS", sector="Industrials", aliases=("United Parcel Service", "UPS"), cik=1090727),
    Company(ticker="BRK-B", sector="Financials", aliases=("Berkshire Hathaway",), cik=1067983),
    Company(ticker="T", sector="Communication Services", aliases=("AT&T",), cik=732717),
]
