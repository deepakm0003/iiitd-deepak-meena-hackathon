"""Event clustering, novelty and corroboration: many articles about one story become one event.

Online, in time order:
  - A document joins the most similar open event with the same key (primary ticker, or MACRO) if cosine
    similarity to the event centroid >= threshold and the event saw a document within `window_hours`.
    Otherwise it opens a new event.
  - Novelty of a document = 1 - max similarity to any earlier document with the same key in the lookback
    window. An event's novelty is the novelty of its first document: the first report is new information,
    follow-ups are not (RavenPack's idea).
  - Corroboration counts independent publishers and source types, weighted by credibility tier.
Threshold and windows are assumptions (A-18) tuned on labelled duplicate pairs in Part 3.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from tripwire.config import load_yaml

WIRE_PUBLISHERS = {"reuters", "bloomberg", "dow jones", "associated press", "ap", "cnbc", "wsj", "wall street journal",
                   "financial times", "ft", "marketwatch", "barron's", "the wall street journal"}


@dataclass
class Event:
    event_id: str
    key: str
    first_seen: datetime
    last_seen: datetime
    centroid: list[float]
    novelty: float
    doc_ids: list[int] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    source_types: set[str] = field(default_factory=set)
    publishers: dict[str, float] = field(default_factory=dict)  # publisher -> credibility

    @property
    def n_docs(self) -> int:
        return len(self.doc_ids)

    @property
    def n_publishers(self) -> int:
        return len(self.publishers)

    @property
    def credibility(self) -> float:
        """Mean credibility of the three most credible independent publishers (v1 factor Q)."""
        top = sorted(self.publishers.values(), reverse=True)[:3]
        return sum(top) / len(top) if top else 0.0

    @property
    def corroboration(self) -> float:
        """min(1, 0.4 + 0.2 * (independent publishers - 1)): 1 source 0.4, 4+ sources 1.0."""
        return min(1.0, 0.4 + 0.2 * max(0, self.n_publishers - 1))


def publisher_of(source: str, url: str | None, hints: dict) -> str:
    name = hints.get("publisher") or hints.get("source_name") or hints.get("feed")
    if not name and url:
        name = urlsplit(url).hostname or ""
    if source == "bluesky":
        name = f"bluesky:{hints.get('author', '?')}"  # each account is its own (weak) publisher
    return (name or source).lower().removeprefix("www.")


def credibility_of(source: str, source_type: str, publisher: str, tiers: dict[str, float]) -> float:
    if source_type == "filing":
        return tiers["filing"]
    if source_type == "regulator":
        return tiers["regulator"]
    if source_type == "social":
        return tiers["social"]
    if any(w in publisher for w in WIRE_PUBLISHERS):
        return tiers["wire_major_press"]
    return tiers["general_news"]


class EventClusterer:
    def __init__(self, threshold: float = 0.72, window_hours: float = 24, lookback_days: float = 7,
                 tiers: dict[str, float] | None = None) -> None:
        self.threshold = threshold
        self.window = timedelta(hours=window_hours)
        self.lookback = timedelta(days=lookback_days)
        self.tiers = tiers or load_yaml("credibility.yaml")["tiers"]
        self.events: dict[str, Event] = {}
        self._history: dict[str, list[tuple[datetime, list[float]]]] = {}  # key -> recent (time, embedding)

    def add(self, raw_id: int, key: str, published_at: datetime, embedding: list[float], source: str,
            source_type: str, url: str | None = None, hints: dict | None = None) -> tuple[Event, float, float]:
        """Assign one document; returns (event, similarity to the event, document novelty)."""
        hints = hints or {}
        history = [h for h in self._history.get(key, []) if published_at - h[0] <= self.lookback]
        novelty = 1.0 - max((_dot(embedding, h[1]) for h in history), default=0.0)
        novelty = max(0.0, min(1.0, novelty))

        best, best_sim = None, -1.0
        for event in self.events.values():
            if event.key != key or published_at - event.last_seen > self.window:
                continue
            sim = _dot(embedding, event.centroid)
            if sim > best_sim:
                best, best_sim = event, sim
        if best is None or best_sim < self.threshold:
            event_id = "evt_" + hashlib.sha1(f"{key}|{raw_id}|{published_at.isoformat()}".encode()).hexdigest()[:12]
            best = Event(event_id, key, published_at, published_at, list(embedding), novelty)
            self.events[event_id] = best
            best_sim = 1.0
        else:
            n = best.n_docs
            best.centroid = _normalise([(c * n + e) / (n + 1) for c, e in zip(best.centroid, embedding, strict=True)])
            best.last_seen = max(best.last_seen, published_at)
        best.doc_ids.append(raw_id)
        best.sources.add(source)
        best.source_types.add(source_type)
        publisher = publisher_of(source, url, hints)
        best.publishers[publisher] = max(best.publishers.get(publisher, 0.0),
                                         credibility_of(source, source_type, publisher, self.tiers))
        self._history[key] = [*history, (published_at, embedding)]
        return best, round(best_sim, 4), round(novelty, 4)


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _normalise(v: list[float]) -> list[float]:
    norm = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / norm for x in v]
