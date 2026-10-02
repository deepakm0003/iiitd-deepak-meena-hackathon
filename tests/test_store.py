from datetime import UTC, datetime

from tripwire.ingestion.normalize import normalize
from tripwire.models import RunStats


def test_insert_is_idempotent(store, make_doc):
    doc = make_doc()
    raw_id = store.add_raw(doc)
    assert isinstance(raw_id, int)
    assert store.add_raw(doc) is None
    # Same article via another feed, with tracking params and www: still a duplicate.
    assert store.add_raw(make_doc(source="gdelt", url="https://example.com/news/bank-liquidity")) is None
    assert store.count_raw() == 1
    assert store.get_raw(raw_id).title == doc.title


def test_count_by_source_and_iter_newest_first(store, make_doc):
    store.add_raw(make_doc(published_at=datetime(2026, 10, 1, tzinfo=UTC)))
    store.add_raw(make_doc(source="edgar", source_type="filing", url=None, external_id="acc-1"))
    assert store.count_raw("edgar") == 1
    assert store.count_raw() == 2
    assert [d.source for d in store.iter_raw()] == ["edgar", "finnhub"]
    assert all(d.published_at.tzinfo is not None for d in store.iter_raw())


def test_documents_are_written_once_per_raw(store, make_doc):
    raw_id = store.add_raw(make_doc())
    doc = normalize(raw_id, store.get_raw(raw_id))
    assert store.add_document(doc) is True
    assert store.add_document(doc) is False
    assert store.count_documents() == 1


def test_unnormalized_ids_skip_documents_and_quarantine(store, make_doc):
    a = store.add_raw(make_doc(url="https://a.example/1"))
    b = store.add_raw(make_doc(url="https://a.example/2"))
    c = store.add_raw(make_doc(url="https://a.example/3"))
    store.add_document(normalize(a, store.get_raw(a)))
    store.add_quarantine("finnhub", "bad", {"raw_id": b}, raw_id=b)
    assert store.raw_ids_without_document() == [c]


def test_checkpoints_upsert(store):
    assert store.get_checkpoint("gdelt") is None
    store.set_checkpoint("gdelt", "20261002020000")
    store.set_checkpoint("gdelt", "20261002021500")
    assert store.get_checkpoint("gdelt") == "20261002021500"


def test_runs_are_recorded(store):
    now = datetime.now(UTC)
    store.record_run(RunStats(source="rbi", started_at=now, finished_at=now, fetched=3, inserted=2, duplicates=1))
    [run] = store.recent_runs()
    assert (run.source, run.inserted, run.duplicates) == ("rbi", 2, 1)


def test_health_reports_backend(store):
    health = store.health()
    assert health["ok"] is True
    assert health["backend"] == "sqlite"
