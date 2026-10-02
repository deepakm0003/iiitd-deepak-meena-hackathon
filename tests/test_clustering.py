from datetime import UTC, datetime, timedelta

import pytest

from tripwire.nlp.clustering import EventClusterer, publisher_of

T0 = datetime(2026, 10, 1, 9, tzinfo=UTC)
TIERS = {"filing": 1.0, "regulator": 1.0, "wire_major_press": 0.9, "general_news": 0.7, "aggregator_blog": 0.5,
         "social": 0.35}
A = [1.0, 0.0, 0.0]          # story A
A2 = [0.96, 0.28, 0.0]       # a rewrite of story A (cosine 0.96)
B = [0.0, 1.0, 0.0]          # an unrelated story


def clusterer():
    return EventClusterer(threshold=0.72, window_hours=24, lookback_days=7, tiers=TIERS)


def test_rewrites_join_one_event_and_count_publishers():
    c = clusterer()
    e1, _, n1 = c.add(1, "JPM", T0, A, "edgar", "filing")
    e2, sim, n2 = c.add(2, "JPM", T0 + timedelta(minutes=20), A2, "finnhub", "news", hints={"publisher": "Reuters"})
    e3, _, _ = c.add(3, "JPM", T0 + timedelta(minutes=40), A2, "gdelt", "news", url="https://www.cnbc.com/x")
    assert e1.event_id == e2.event_id == e3.event_id and sim == pytest.approx(0.96)
    assert e1.n_docs == 3 and e1.n_publishers == 3
    assert e1.corroboration == pytest.approx(0.8)
    assert e1.credibility == pytest.approx((1.0 + 0.9 + 0.9) / 3)
    assert n1 == 1.0 and n2 == pytest.approx(0.04)  # first report is novel; the rewrite is not


def test_different_story_or_company_opens_a_new_event():
    c = clusterer()
    a, _, _ = c.add(1, "JPM", T0, A, "finnhub", "news")
    b, _, novelty = c.add(2, "JPM", T0, B, "finnhub", "news")
    other, _, _ = c.add(3, "BAC", T0, A, "finnhub", "news")
    assert len({a.event_id, b.event_id, other.event_id}) == 3
    assert novelty == 1.0


def test_old_events_close_but_novelty_remembers_a_week():
    c = clusterer()
    first, _, _ = c.add(1, "JPM", T0, A, "finnhub", "news")
    later, _, novelty = c.add(2, "JPM", T0 + timedelta(hours=30), A, "finnhub", "news")
    assert later.event_id != first.event_id      # outside the 24 h window: a new event...
    assert novelty == pytest.approx(0.0)         # ...but not new information
    _, _, fresh = c.add(3, "JPM", T0 + timedelta(days=9), A, "finnhub", "news")
    assert fresh == pytest.approx(1.0)           # beyond the 7-day lookback it counts as new again


def test_cluster_all_is_deterministic_and_idempotent(store, make_doc):
    from tripwire.ingestion.normalize import normalize
    from tripwire.nlp.cluster_run import cluster_all
    from tripwire.nlp.engine import Annotation

    vectors = [A, A2, B]
    annotations = []
    for i, vec in enumerate(vectors):
        raw_id = store.add_raw(make_doc(url=f"https://e.com/{i}", published_at=T0 + timedelta(minutes=i)))
        doc = normalize(raw_id, store.get_raw(raw_id))
        store.add_document(doc)
        annotations.append(Annotation(
            raw_id=raw_id, dedup_key=doc.dedup_key, source="finnhub", source_type="news",
            published_at=doc.published_at, primary="JPM", entities=[], event_type="Other", event_subtype=None,
            event_method="head", event_confidence=0.5, sentiment=0.0, sentiment_label="neutral",
            sentiment_method="sentence", embedding=vec, annotated_at=T0))
    store.add_annotations(annotations)
    first = cluster_all(store, clusterer())
    ids_first = sorted(e["event_id"] for e in store.get_events())
    second = cluster_all(store, clusterer())
    assert first == second and sorted(e["event_id"] for e in store.get_events()) == ids_first
    assert first["events"] == 2 and first["multi_document_events"] == 1


def test_publisher_identity():
    assert publisher_of("gdelt", "https://www.reuters.com/a", {"source_name": "reuters.com"}) == "reuters.com"
    assert publisher_of("finnhub", "https://finnhub.io/x", {"publisher": "Yahoo"}) == "yahoo"
    assert publisher_of("bluesky", None, {"author": "ab12"}) == "bluesky:ab12"
