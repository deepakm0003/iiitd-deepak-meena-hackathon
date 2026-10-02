"""Recompute events from all annotations (deterministic, idempotent) and store them."""

from datetime import datetime

from tripwire.nlp.clustering import EventClusterer


def cluster_all(store, clusterer: EventClusterer | None = None) -> dict:
    clusterer = clusterer or EventClusterer()
    annotations = sorted(store.get_annotations(), key=lambda a: (a["published_at"], a["raw_id"]))
    urls = {d.raw_id: (d.url, d.hints) for d in store.iter_documents()}
    members = []
    for a in annotations:
        url, hints = urls.get(a["raw_id"], (None, {}))
        key = a["primary"]  # ticker, MACRO or NONE
        event, similarity, novelty = clusterer.add(
            a["raw_id"], key, datetime.fromisoformat(a["published_at"]), a["embedding"], a["source"],
            a["source_type"], url, hints,
        )
        members.append({"raw_id": a["raw_id"], "event_id": event.event_id, "similarity": similarity,
                        "novelty": novelty})
    event_rows = [
        {
            "event_id": e.event_id,
            "key": e.key,
            "first_seen": e.first_seen,
            "last_seen": e.last_seen,
            "n_docs": e.n_docs,
            "n_publishers": e.n_publishers,
            "novelty": round(e.novelty, 4),
            "corroboration": round(e.corroboration, 4),
            "credibility": round(e.credibility, 4),
            "detail": {
                "sources": sorted(e.sources),
                "source_types": sorted(e.source_types),
                "publishers": {k: round(v, 2) for k, v in sorted(e.publishers.items())},
                "doc_ids": e.doc_ids,
            },
        }
        for e in clusterer.events.values()
    ]
    store.replace_events(event_rows, members)
    multi = [e for e in event_rows if e["n_docs"] > 1]
    return {
        "documents": len(annotations),
        "events": len(event_rows),
        "multi_document_events": len(multi),
        "largest_event": max((e["n_docs"] for e in event_rows), default=0),
        "dedup_ratio": round(len(annotations) / max(1, len(event_rows)), 3),
    }
