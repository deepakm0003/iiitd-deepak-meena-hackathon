"""Official RSS feeds (RBI press releases, Federal Reserve press releases).

Some feeds publish dates without a timezone (RBI uses IST), so each feed declares its UTC offset.
Cursor: newest published time seen (ISO).
"""

from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from tripwire.ingestion.http import HttpClient
from tripwire.models import RawDocument
from tripwire.ports.source import FetchResult


def parse_feed_date(value: str, utc_offset_minutes: int) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(minutes=utc_offset_minutes)))
    return parsed.astimezone(UTC)


class RssSource:
    def __init__(self, http: HttpClient, feed_cfg: dict[str, Any]) -> None:
        self.http = http
        self.name = feed_cfg["name"]
        self.url = feed_cfg["url"]
        self.source_type = feed_cfg.get("source_type", "regulator")
        self.offset = int(feed_cfg.get("utc_offset_minutes", 0))

    def fetch(self, cursor: str | None) -> FetchResult:
        since = datetime.fromisoformat(cursor) if cursor else None
        feed = feedparser.parse(self.http.get(self.url).content)
        documents, newest = [], since
        for entry in feed.entries:
            stamp = entry.get("published") or entry.get("updated")
            title = (entry.get("title") or "").strip()
            if not stamp or not title:
                continue
            published = parse_feed_date(stamp, self.offset)
            if since and published <= since:
                continue
            documents.append(
                RawDocument(
                    source=self.name,
                    source_type=self.source_type,
                    title=title,
                    text=entry.get("summary") or "",
                    url=entry.get("link") or None,
                    external_id=entry.get("id") or None,
                    published_at=published,
                    payload={"feed": self.name, "tags": [t.get("term") for t in entry.get("tags", [])][:10]},
                )
            )
            newest = max(newest, published) if newest else published
        return FetchResult(documents, newest.isoformat() if newest else cursor)
