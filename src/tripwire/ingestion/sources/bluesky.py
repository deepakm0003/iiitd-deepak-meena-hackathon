"""Bluesky public posts via Jetstream (no account or key needed).

Each fetch listens for `window_seconds`, keeps posts that mention a universe cashtag, or a company alias
together with a finance keyword, then returns. The cursor is Jetstream's time_us, so the next window
resumes exactly where this one stopped (Jetstream can replay recent history from a cursor).

Privacy: author DIDs are replaced by a short one-way hash and no post URL is stored.
"""

import asyncio
import hashlib
import json
import re
import socket
import time
from datetime import UTC, datetime
from typing import Any

import websockets

from tripwire.ingestion.matching import NameMatcher
from tripwire.models import RawDocument
from tripwire.ports.source import FetchResult


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


class PostFilter:
    def __init__(self, matcher: NameMatcher, keywords: list[str], languages: list[str]) -> None:
        self.matcher = matcher
        self.languages = set(languages)
        self.keywords = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE)

    def match(self, record: dict[str, Any]) -> set[str]:
        text = record.get("text") or ""
        langs = set(record.get("langs") or [])
        if not text or (self.languages and langs and not langs & self.languages):
            return set()
        tickers = self.matcher.cashtags(text)
        if not tickers and self.keywords.search(text):
            tickers = self.matcher.find(text)
        return tickers


def post_to_document(event: dict[str, Any], tickers: set[str]) -> RawDocument:
    commit = event["commit"]
    record = commit["record"]
    text = record.get("text", "")
    did = event["did"]
    return RawDocument(
        source="bluesky",
        source_type="social",
        title=" ".join(text.split())[:280],
        text=text,
        url=None,
        external_id=short_hash(f"{did}/{commit.get('rkey', '')}", 32),
        published_at=datetime.fromtimestamp(event["time_us"] / 1_000_000, UTC),
        payload={
            "author": short_hash(did),
            "tickers": sorted(tickers),
            "langs": record.get("langs") or [],
            "created_at": record.get("createdAt"),
            "lang": (record.get("langs") or ["en"])[0],
        },
    )


class BlueskySource:
    name = "bluesky"
    source_type = "social"

    def __init__(
        self,
        cfg: dict[str, Any],
        post_filter: PostFilter,
        window_seconds: float | None = None,
        force_ipv4: bool = False,
    ) -> None:
        self.endpoint = cfg["endpoint"]
        self.connect_kwargs = {"family": socket.AF_INET} if force_ipv4 else {}
        self.window = float(window_seconds or cfg.get("window_seconds", 60))
        self.filter = post_filter

    def fetch(self, cursor: str | None) -> FetchResult:
        documents, last = asyncio.run(self._listen(cursor))
        return FetchResult(documents, str(last) if last else cursor)

    async def _listen(self, cursor: str | None) -> tuple[list[RawDocument], int | None]:
        url = f"{self.endpoint}?wantedCollections=app.bsky.feed.post"
        if cursor:
            url += f"&cursor={cursor}"
        documents: list[RawDocument] = []
        last: int | None = int(cursor) if cursor else None
        deadline = time.monotonic() + self.window
        async with websockets.connect(url, open_timeout=20, max_size=2**21, **self.connect_kwargs) as ws:
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except TimeoutError:
                    break
                event = json.loads(message)
                last = event.get("time_us", last)
                commit = event.get("commit") or {}
                if (
                    event.get("kind") == "commit"
                    and commit.get("operation") == "create"
                    and commit.get("collection") == "app.bsky.feed.post"
                    and (tickers := self.filter.match(commit.get("record") or {}))
                ):
                    documents.append(post_to_document(event, tickers))
        return documents, last
