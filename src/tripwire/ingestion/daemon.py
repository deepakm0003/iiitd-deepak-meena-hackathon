"""Long-running collection loop (used on the server inside tmux).

- Each polling source runs on its own interval; Bluesky streams in a separate thread in back-to-back windows.
- Circuit breaker: after 3 consecutive failures a source pauses for 30 minutes instead of hammering a
  struggling API; it resumes automatically.
- After every pass the normaliser drains the queue, and var/collector_status.json is rewritten for the
  ops view (per-source last run, totals, failures, next run).
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tripwire.ingestion.runner import requeue_unnormalized, run_normalizer, run_source
from tripwire.ports import Queue, Source, Store

log = logging.getLogger(__name__)
TRIP_AFTER = 3
TRIP_FOR = timedelta(minutes=30)


@dataclass
class Scheduled:
    source: Source
    interval: timedelta
    next_due: datetime = field(default_factory=lambda: datetime.now(UTC))
    failures: int = 0
    paused_until: datetime | None = None
    runs: int = 0
    inserted: int = 0
    last_status: str | None = None
    last_error: str | None = None
    last_run: datetime | None = None

    def record(self, status: str, inserted: int, error: str | None, now: datetime) -> None:
        self.runs += 1
        self.inserted += inserted
        self.last_status, self.last_error, self.last_run = status, error, now
        self.next_due = now + self.interval
        if status == "ok":
            self.failures, self.paused_until = 0, None
        else:
            self.failures += 1
            if self.failures >= TRIP_AFTER:
                self.paused_until = now + TRIP_FOR
                log.warning("%s paused until %s after %d failures", self.source.name, self.paused_until, self.failures)

    def due(self, now: datetime) -> bool:
        return now >= self.next_due and not (self.paused_until and now < self.paused_until)

    def as_dict(self) -> dict:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {
            "interval_minutes": self.interval.total_seconds() / 60,
            "runs": self.runs,
            "inserted_total": self.inserted,
            "last_run": iso(self.last_run),
            "last_status": self.last_status,
            "last_error": self.last_error,
            "consecutive_failures": self.failures,
            "paused_until": iso(self.paused_until),
            "next_due": iso(self.next_due),
        }


def run_daemon(
    store: Store,
    queue: Queue,
    polled: list[Scheduled],
    streaming: Scheduled | None,
    status_path: Path,
    stop: threading.Event,
    tick_seconds: float = 5.0,
) -> None:
    log.info("requeued %d raw documents awaiting normalisation", requeue_unnormalized(store, queue))
    threads = []
    if streaming:
        threads.append(threading.Thread(target=_stream_loop, args=(store, queue, streaming, stop), daemon=True))
        threads[-1].start()
    while not stop.is_set():
        now = datetime.now(UTC)
        for item in polled:
            if item.due(now):
                stats = run_source(store, queue, item.source)
                item.record(stats.status, stats.inserted, stats.error, datetime.now(UTC))
                log.info("%s: %s fetched=%d new=%d dup=%d", item.source.name, stats.status,
                         stats.fetched, stats.inserted, stats.duplicates)
        counts = run_normalizer(store, queue)
        if any(counts.values()):
            log.info("normaliser: %s", counts)
        _write_status(status_path, store, queue, [*polled, *([streaming] if streaming else [])])
        stop.wait(tick_seconds)
    for thread in threads:
        thread.join(timeout=120)


def _stream_loop(store: Store, queue: Queue, item: Scheduled, stop: threading.Event) -> None:
    while not stop.is_set():
        now = datetime.now(UTC)
        if not item.due(now):
            stop.wait(10)
            continue
        stats = run_source(store, queue, item.source)
        item.record(stats.status, stats.inserted, stats.error, datetime.now(UTC))
        item.next_due = datetime.now(UTC)  # streaming: start the next window immediately
        if stats.status != "ok":
            stop.wait(min(60 * item.failures, 300))  # back off on reconnect failures


def _write_status(path: Path, store: Store, queue: Queue, items: list[Scheduled]) -> None:
    status = {
        "updated_at": datetime.now(UTC).isoformat(),
        "store": store.health(),
        "queue": queue.health(),
        "sources": {i.source.name: i.as_dict() for i in items},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
    tmp.replace(path)
