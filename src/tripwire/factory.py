"""Build the adapters and sources selected by the settings (lite vs full mode, replay vs live)."""

import logging
from datetime import timedelta

from tripwire.adapters.memory_queue import MemoryQueue
from tripwire.adapters.sql_store import SqlStore
from tripwire.config import load_yaml
from tripwire.ingestion.http import HttpClient, TokenBucket
from tripwire.ingestion.matching import NameMatcher
from tripwire.ingestion.sources.bluesky import BlueskySource, PostFilter
from tripwire.ingestion.sources.edgar import EdgarSource
from tripwire.ingestion.sources.finnhub import FinnhubSource
from tripwire.ingestion.sources.gdelt import GdeltSource
from tripwire.ingestion.sources.replay import ReplaySource
from tripwire.ingestion.sources.rss import RssSource
from tripwire.ports import Queue, Source, Store
from tripwire.settings import Settings
from tripwire.universe import load_universe

log = logging.getLogger(__name__)
LIVE_SOURCES = ("gdelt", "finnhub", "edgar", "rss", "bluesky")


def build_store(settings: Settings) -> Store:
    store = SqlStore(settings.database_url)
    store.init()
    return store


def build_queue(settings: Settings) -> Queue:
    if settings.queue == "memory":
        return MemoryQueue()
    raise NotImplementedError("Redis Streams adapter arrives with full mode (Part 1f)")


def build_http(settings: Settings) -> HttpClient:
    sources_cfg = load_yaml("sources.yaml")
    sec = TokenBucket(float(sources_cfg["edgar"]["requests_per_second"]), burst=2)  # SEC's limit is per user
    limits = {
        "data.gdeltproject.org": TokenBucket(0.5, burst=1),
        "finnhub.io": TokenBucket(float(sources_cfg["finnhub"]["calls_per_minute"]) / 60, burst=5),
        "www.sec.gov": sec,
        "data.sec.gov": sec,
        "www.rbi.org.in": TokenBucket(0.5, burst=1),
        "www.federalreserve.gov": TokenBucket(0.5, burst=1),
    }
    agent = settings.sec_user_agent or "Tripwire research (contact not configured)"
    return HttpClient(user_agent=agent, limits=limits, force_ipv4=settings.force_ipv4)


def build_sources(
    settings: Settings, names: list[str] | None, live: bool, bluesky_seconds: float | None = None
) -> tuple[list[tuple[Source, timedelta]], tuple[Source, timedelta] | None]:
    """Return (polled sources with intervals, streaming source or None)."""
    if not live:
        return [(ReplaySource(settings.data_dir / "replay"), timedelta(minutes=1))], None
    cfg = load_yaml("sources.yaml")
    wanted = names or list(LIVE_SOURCES)
    unknown = set(wanted) - set(LIVE_SOURCES)
    if unknown:
        raise ValueError(f"unknown sources: {sorted(unknown)}; choose from {LIVE_SOURCES}")
    companies = load_universe()
    matcher = NameMatcher(companies)
    http = build_http(settings)
    minutes = lambda key: timedelta(minutes=float(cfg[key]["interval_minutes"]))  # noqa: E731
    polled: list[tuple[Source, timedelta]] = []
    streaming = None
    if "gdelt" in wanted:
        polled.append((GdeltSource(http, cfg["gdelt"], matcher), minutes("gdelt")))
    if "finnhub" in wanted:
        if settings.finnhub_api_key:
            key = settings.finnhub_api_key.get_secret_value()
            tickers = [c.ticker for c in companies]
            polled.append((FinnhubSource(http, key, tickers, cfg["finnhub"]), minutes("finnhub")))
        else:
            log.warning("FINNHUB_API_KEY not set: skipping finnhub")
    if "edgar" in wanted:
        if not settings.sec_user_agent:
            raise ValueError("SEC_USER_AGENT must be set (SEC requires a contact User-Agent)")
        if not any(c.cik for c in companies):
            raise ValueError("universe has no CIKs: run `python -m tripwire universe --refresh` first")
        items = load_yaml("edgar_items.yaml")["items"]
        polled.append((EdgarSource(http, companies, items, cfg["edgar"]), minutes("edgar")))
    if "rss" in wanted:
        for feed in cfg["rss"]["feeds"]:
            polled.append((RssSource(http, feed), minutes("rss")))
    if "bluesky" in wanted:
        bcfg = cfg["bluesky"]
        post_filter = PostFilter(matcher, bcfg["finance_keywords"], bcfg.get("languages", ["en"]))
        bluesky = BlueskySource(bcfg, post_filter, bluesky_seconds, force_ipv4=settings.force_ipv4)
        streaming = (bluesky, timedelta(seconds=0))
    return polled, streaming
