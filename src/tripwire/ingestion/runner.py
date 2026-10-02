"""Collection runner: sources -> raw store -> queue -> normaliser -> documents.

Delivery guarantees
- Checkpoints are saved only after a fetch's documents are stored, so a crash means re-fetching, never
  losing data; re-fetched items are no-ops thanks to the unique dedup key (at-least-once + idempotent).
- The normaliser acks a message only after the document is written. Unusable records are quarantined and
  acked; unexpected errors are nacked (retried, then dead-lettered).
- On start-up, raw documents that were stored but never normalised are re-queued (covers a crash of the
  in-memory queue in lite mode).
"""

import logging
from datetime import UTC, datetime

from tripwire.ingestion.normalize import NormalizationError, normalize
from tripwire.models import RunStats
from tripwire.ports import Queue, Source, Store

log = logging.getLogger(__name__)
RAW_STREAM = "docs.raw"
NORM_STREAM = "docs.norm"
NORMALIZER_GROUP = "normalizer"


def run_source(store: Store, queue: Queue, source: Source) -> RunStats:
    stats = RunStats(source=source.name, started_at=datetime.now(UTC))
    try:
        result = source.fetch(store.get_checkpoint(source.name))
        for doc in result.documents:
            stats.fetched += 1
            raw_id = store.add_raw(doc)
            if raw_id is None:
                stats.duplicates += 1
            else:
                stats.inserted += 1
                queue.publish(RAW_STREAM, {"raw_id": raw_id})
        store.set_checkpoint(source.name, result.cursor)
    except Exception as exc:
        stats.status = "error"
        stats.error = f"{type(exc).__name__}: {exc}"[:500]
        log.exception("source %s failed", source.name)
    stats.finished_at = datetime.now(UTC)
    store.record_run(stats)
    return stats


def requeue_unnormalized(store: Store, queue: Queue, limit: int = 100_000) -> int:
    ids = store.raw_ids_without_document(limit)
    for raw_id in ids:
        queue.publish(RAW_STREAM, {"raw_id": raw_id})
    return len(ids)


def run_normalizer(store: Store, queue: Queue, consumer: str = "normalizer-1", batch: int = 200) -> dict[str, int]:
    counts = {"normalized": 0, "quarantined": 0, "failed": 0}
    while messages := queue.consume(RAW_STREAM, NORMALIZER_GROUP, consumer, count=batch):
        for message in messages:
            raw_id = int(message.data["raw_id"])
            raw = None
            try:
                raw = store.get_raw(raw_id)
                if raw is None:
                    raise NormalizationError(f"raw document {raw_id} not found")
                if store.add_document(normalize(raw_id, raw)):
                    queue.publish(NORM_STREAM, {"raw_id": raw_id})
                counts["normalized"] += 1
                queue.ack(RAW_STREAM, NORMALIZER_GROUP, message.id)
            except NormalizationError as exc:
                store.add_quarantine(
                    raw.source if raw else "unknown",
                    str(exc),
                    {"raw_id": raw_id, "title": (raw.title[:200] if raw else None)},
                    raw_id=raw_id,
                )
                counts["quarantined"] += 1
                queue.ack(RAW_STREAM, NORMALIZER_GROUP, message.id)
            except Exception as exc:
                counts["failed"] += 1
                log.exception("normaliser failed on raw_id=%s", raw_id)
                queue.nack(RAW_STREAM, NORMALIZER_GROUP, message.id, error=f"{type(exc).__name__}: {exc}")
    return counts
