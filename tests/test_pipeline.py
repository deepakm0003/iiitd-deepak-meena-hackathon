from datetime import UTC, datetime, timedelta

import pytest

from tripwire.adapters.memory_queue import MemoryQueue
from tripwire.ingestion.normalize import NormalizationError, make_lead, normalize
from tripwire.ingestion.replay_export import export_replay
from tripwire.ingestion.runner import RAW_STREAM, requeue_unnormalized, run_normalizer, run_source
from tripwire.ingestion.sources.replay import ReplaySource
from tripwire.models import RawDocument
from tripwire.ports.source import FetchResult


class FakeSource:
    name = "fake"
    source_type = "news"

    def __init__(self, docs, fail=False):
        self.docs, self.fail, self.cursors = docs, fail, []

    def fetch(self, cursor):
        self.cursors.append(cursor)
        if self.fail:
            raise RuntimeError("upstream down")
        return FetchResult(self.docs, f"c{len(self.cursors)}")


# ---------------------------------------------------------------- normalisation
def test_normalize_cleans_html_and_builds_lead(make_doc):
    raw = make_doc(title="JPMorgan &amp;amp; peers <b>slide</b>",
                   text="<p>Shares fell 4%. Analysts cut targets. A third sentence.</p>")
    doc = normalize(1, raw)
    assert doc.title == "JPMorgan & peers slide"
    assert doc.lead == "Shares fell 4%. Analysts cut targets."
    assert doc.url == "https://example.com/news/bank-liquidity"


def test_normalize_social_strips_mentions_and_links(make_doc):
    raw = make_doc(source="bluesky", source_type="social", url=None,
                   title="@alice.bsky.social $JPM to the moon https://x.co/1", payload={"lang": "en"})
    assert normalize(1, raw).title == "@user $JPM to the moon"


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"title": "   "}, "empty title"),
        ({"published_at": datetime.now(UTC) + timedelta(days=1)}, "future"),
        ({"payload": {"lang": "pt"}}, "non-English"),
    ],
)
def test_normalize_rejects_unusable_records(make_doc, overrides, reason):
    with pytest.raises(NormalizationError, match=reason):
        normalize(1, make_doc(**overrides))


def test_clean_text_repairs_broken_apostrophes():
    from tripwire.ingestion.normalize import clean_text

    assert clean_text("Amazon\ufffds former highs") == "Amazon's former highs"
    assert clean_text("Price \ufffd up") == "Price up"


def test_make_lead_truncates_long_text():
    assert len(make_lead("word " * 400)) <= 600


# ---------------------------------------------------------------- runner
def test_rerun_inserts_nothing_new_and_checkpoint_advances(store, make_doc):
    queue = MemoryQueue()
    source = FakeSource([make_doc(), make_doc(url="https://example.com/2")])
    first = run_source(store, queue, source)
    second = run_source(store, queue, source)
    assert (first.inserted, first.duplicates) == (2, 0)
    assert (second.inserted, second.duplicates) == (0, 2)
    assert source.cursors == [None, "c1"]
    assert store.get_checkpoint("fake") == "c2"


def test_failed_fetch_keeps_checkpoint_and_is_recorded(store):
    store.set_checkpoint("fake", "c-before")
    stats = run_source(store, MemoryQueue(), FakeSource([], fail=True))
    assert stats.status == "error" and "upstream down" in stats.error
    assert store.get_checkpoint("fake") == "c-before"
    assert store.recent_runs()[0].status == "error"


def test_normalizer_writes_documents_and_quarantines_bad_records(store, make_doc):
    queue = MemoryQueue()
    run_source(store, queue, FakeSource([make_doc(), make_doc(url="https://e.com/pt", payload={"lang": "pt"})]))
    counts = run_normalizer(store, queue)
    assert counts == {"normalized": 1, "quarantined": 1, "failed": 0}
    assert store.count_documents() == 1 and store.count_quarantine() == 1
    assert queue.health()["pending"] == 0
    assert len(queue.consume("docs.norm", "nlp", "w")) == 1


def test_requeue_recovers_documents_lost_by_a_crashed_queue(store, make_doc):
    run_source(store, MemoryQueue(), FakeSource([make_doc()]))  # this queue is "lost"
    fresh = MemoryQueue()
    assert requeue_unnormalized(store, fresh) == 1
    run_normalizer(store, fresh)
    assert store.count_documents() == 1
    assert requeue_unnormalized(store, MemoryQueue()) == 0


def test_unexpected_errors_are_retried_then_dead_lettered(store, make_doc, monkeypatch):
    queue = MemoryQueue()
    run_source(store, queue, FakeSource([make_doc()]))
    monkeypatch.setattr(store, "add_document", lambda doc: (_ for _ in ()).throw(OSError("disk full")))
    counts = run_normalizer(store, queue)
    assert counts["failed"] == 3
    assert len(queue.dead_letters(RAW_STREAM)) == 1


# ---------------------------------------------------------------- replay
def test_export_then_replay_round_trip(store, make_doc, tmp_path):
    for i in range(3):
        store.add_raw(make_doc(url=f"https://e.com/{i}", text="x" * 2000,
                               published_at=datetime(2026, 10, 1, i, tzinfo=UTC)))
    out = tmp_path / "replay" / "captured.jsonl"
    assert export_replay(store, out, ["finnhub"], per_source=2) == {"finnhub": 2}
    replay = ReplaySource(out.parent, batch_size=10)
    result = replay.fetch(None)
    assert [d.published_at.hour for d in result.documents] == [1, 2]   # newest two, replayed in time order
    assert all(len(d.text) == 600 for d in result.documents)
    assert replay.fetch(result.cursor).documents == []
    assert all(isinstance(d, RawDocument) for d in result.documents)


def test_daemon_picks_up_documents_inserted_by_other_processes(store, make_doc, tmp_path, monkeypatch):
    import threading

    from tripwire.ingestion import daemon

    monkeypatch.setattr(daemon, "REQUEUE_EVERY", timedelta(0))
    queue = MemoryQueue()
    stop = threading.Event()
    calls = {"n": 0}

    class Inserter:  # simulates another process inserting while the daemon runs
        name, source_type = "other", "news"

        def fetch(self, cursor):
            calls["n"] += 1
            if calls["n"] >= 2:
                stop.set()
            store.add_raw(make_doc(url=f"https://e.com/other/{calls['n']}"))  # bypasses this daemon's queue
            return FetchResult([], None)

    item = daemon.Scheduled(Inserter(), timedelta(0))
    daemon.run_daemon(store, queue, [item], None, tmp_path / "status.json", stop, tick_seconds=0)
    run_normalizer(store, queue)
    assert store.count_documents() == 2
    assert (tmp_path / "status.json").exists()
