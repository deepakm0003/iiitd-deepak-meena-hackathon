"""Finnhub company news (per ticker) and general market news. Free tier: 60 calls/min; we use 50.

The API key goes in the X-Finnhub-Token header so it never appears in URLs or logs.
Cursor: {"last": {ticker: newest unix time seen}, "general_min_id": newest general-news id}.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tripwire.ingestion.http import HttpClient, HttpError
from tripwire.models import RawDocument
from tripwire.ports.source import FetchResult

log = logging.getLogger(__name__)
BASE = "https://finnhub.io/api/v1"


class FinnhubSource:
    name = "finnhub"
    source_type = "news"

    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        tickers: list[str],
        cfg: dict[str, Any],
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self.http = http
        self._headers = {"X-Finnhub-Token": api_key}
        self.tickers = tickers
        self.lookback = timedelta(days=int(cfg.get("lookback_days", 3)))
        self.general_news = bool(cfg.get("general_news", True))
        self._today = today

    def fetch(self, cursor: str | None) -> FetchResult:
        state = json.loads(cursor) if cursor else {}
        last: dict[str, int] = state.get("last", {})
        general_min_id = int(state.get("general_min_id", 0))
        today = self._today()
        documents: list[RawDocument] = []
        failures = 0
        for ticker in self.tickers:
            try:
                items = self.http.get(
                    f"{BASE}/company-news",
                    params={"symbol": ticker.replace("-", "."), "from": str(today - self.lookback), "to": str(today)},
                    headers=self._headers,
                ).json()
            except HttpError as exc:
                failures += 1
                log.warning("finnhub %s failed: %s", ticker, exc)
                continue
            newest = last.get(ticker, 0)
            for item in items:
                if int(item.get("datetime", 0)) > last.get(ticker, 0) and (doc := self._doc(item, ticker)):
                    documents.append(doc)
                    newest = max(newest, int(item["datetime"]))
            last[ticker] = newest
        if self.tickers and failures == len(self.tickers):
            raise RuntimeError("all Finnhub company-news requests failed")
        if self.general_news:
            items = self.http.get(
                f"{BASE}/news", params={"category": "general", "minId": general_min_id}, headers=self._headers
            ).json()
            for item in items:
                if int(item.get("id", 0)) > general_min_id and (doc := self._doc(item, None)):
                    documents.append(doc)
            general_min_id = max([general_min_id, *(int(i.get("id", 0)) for i in items)])
        return FetchResult(documents, json.dumps({"last": last, "general_min_id": general_min_id}))

    def _doc(self, item: dict[str, Any], ticker: str | None) -> RawDocument | None:
        headline = (item.get("headline") or "").strip()
        if not headline or not item.get("datetime"):
            return None
        related = [t.strip() for t in (item.get("related") or "").split(",") if t.strip()]
        return RawDocument(
            source=self.name,
            source_type="news",
            title=headline,
            text=item.get("summary") or "",
            url=item.get("url") or None,
            external_id=str(item["id"]) if item.get("id") else None,
            published_at=datetime.fromtimestamp(int(item["datetime"]), UTC),
            payload={
                "publisher": item.get("source"),
                "category": item.get("category"),
                "related": related,
                "query_ticker": ticker,
            },
        )
