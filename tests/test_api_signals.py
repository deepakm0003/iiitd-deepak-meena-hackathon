"""Signals contract and API, end to end on a tiny store (fake annotations, real clustering and scoring)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tripwire.api.app import create_app
from tripwire.ingestion.normalize import normalize
from tripwire.nlp.engine import Annotation, EntityAnnotation
from tripwire.scoring.impact import FACTORS, ImpactModel
from tripwire.scoring.pipeline import score_cycle
from tripwire.scoring.signals import risk_level

NOW = datetime.now(UTC).replace(microsecond=0)
WEIGHTS = dict(zip(FACTORS, [0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.5], strict=True))


@pytest.fixture
def filled_store(store, make_doc):
    vectors = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    specs = [("a", "JPM", "Credit Event", -0.8, 0), ("a", "JPM", "Credit Event", -0.7, 5), ("b", "MACRO",
             "Macroeconomic", 0.2, 10)]
    annotations = []
    for i, (vec, key, etype, sent, minutes) in enumerate(specs):
        raw_id = store.add_raw(make_doc(url=f"https://news{i}.example/x", title=f"Story {i}",
                                        published_at=NOW - timedelta(hours=1) + timedelta(minutes=minutes)))
        doc = normalize(raw_id, store.get_raw(raw_id))
        store.add_document(doc)
        jpm = EntityAnnotation(ticker="JPM", cik=19617, sector="Financials", link_confidence=0.98,
                               relevance=0.9, in_title=True, method="long_alias", sentiment=sent)
        ents = [jpm] if key == "JPM" else []
        annotations.append(Annotation(
            raw_id=raw_id, dedup_key=doc.dedup_key, source="finnhub", source_type="news",
            published_at=doc.published_at, primary=key, entities=ents, event_type=etype, event_subtype=None,
            event_method="rule:bankruptcy" if key == "JPM" else "head", event_confidence=0.9, sentiment=sent,
            sentiment_label="negative", sentiment_method="entity_pair", embedding=vectors[vec], annotated_at=NOW,
            sentiment_evidence=[{"text": f"Story {i}", "score": sent, "location": "title"}]))
    store.add_annotations(annotations)
    return store


@pytest.fixture
def model():
    return ImpactModel(weights=WEIGHTS, h_table={"Credit Event": 0.9, "Macroeconomic": 0.2, "__default__": 0.3},
                       calibration_adjusted=[i / 100 for i in range(100)],
                       calibration_period=("2023-01-01", "2025-06-30"))


def test_score_cycle_produces_contract_compliant_signals(filled_store, model, tmp_path):
    stats = score_cycle(filled_store, model, tmp_path / "signals.jsonl")
    assert stats["events"] == 2 and stats["signals"] == 2
    jpm = filled_store.query_signals(entity="JPM")[0]
    for field in ("sentiment_score", "event_type", "impact_score", "confidence", "explanation", "evidence",
                  "impact_breakdown", "config_hash", "provenance"):
        assert field in jpm
    assert -1 <= jpm["sentiment_score"] <= 1 and 1 <= jpm["impact_score"] <= 10
    assert jpm["corroboration"]["n_articles"] == 2 and jpm["event_type"] == "Credit Event"
    assert "Impact" in jpm["explanation"] and jpm["company"]["sector"] == "Financials"
    assert len((tmp_path / "signals.jsonl").read_text().splitlines()) == 2
    # Re-running without changes updates nothing (the WebSocket only pushes real changes).
    assert score_cycle(filled_store, model)["signals_changed"] == 0
    # A stale signal (its event no longer exists) is pruned.
    filled_store.upsert_signals([{**jpm, "event_id": "evt_stale"}])
    score_cycle(filled_store, model)
    assert filled_store.get_signal("evt_stale") is None


def test_api_endpoints(filled_store, model):
    score_cycle(filled_store, model)
    client = TestClient(create_app(filled_store))
    assert client.get("/health").json()["status"] == "ok"
    listed = client.get("/signals", params={"min_impact": 1}).json()
    assert len(listed) == 2
    one = client.get(f"/signals/{listed[0]['event_id']}")
    assert one.status_code == 200 and one.json()["event_id"] == listed[0]["event_id"]
    assert client.get("/signals/evt_missing").status_code == 404
    assert client.get("/signals", params={"event_type": "Nonsense"}).status_code == 422
    stats = client.get("/signals/stats", params={"days": 7}).json()
    assert stats["total"] == 2 and sum(stats["by_type"].values()) == 2
    assert sum(d["total"] for d in stats["by_day"]) == 2
    assert all(s["event_type"] != "Other" for s in client.get("/signals", params={"exclude_other": True}).json())
    risk = client.get("/companies/jpm/risk").json()
    assert risk["n_events"] == 1 and risk["by_event_type"] == {"Credit Event": 1}
    assert client.get("/companies/XXXX/risk").status_code == 404


def test_risk_levels():
    levels = {"low": 4.0, "medium": 7.0, "high": 8.5}
    assert risk_level(9.0, levels) == ("Critical", "Flash")
    assert risk_level(7.2, levels) == ("High", "Urgent")
    assert risk_level(5.0, levels) == ("Medium", "Watch")
    assert risk_level(2.0, levels) == ("Low", "Log")


def test_favourable_news_is_material_but_not_a_critical_risk_alert():
    levels = {"high": 8.0, "medium": 6.0, "low": 4.0}
    assert risk_level(9.5, levels, "adverse")[0] == "Critical"
    assert risk_level(9.5, levels, "neutral")[0] == "Critical"
    assert risk_level(9.5, levels, "favourable") == ("Medium", "Watch")
    assert risk_level(3.0, levels, "favourable")[0] == "Low"


def test_alert_tier_follows_the_measured_sources():
    from tripwire.scoring.signals import alert_tier

    confirmed = {"8k_item", "rule:launch"}
    assert alert_tier("8k_item:2.02", "Earnings", confirmed) == "confirmed"
    assert alert_tier("rule:launch", "Product Launch", confirmed) == "confirmed"
    assert alert_tier("head+zs", "Credit Event", confirmed) == "standard"
    assert alert_tier("rule:legal", "Regulatory/Legal", confirmed) == "standard"
    assert alert_tier("head:abstain", "Other", confirmed) == "none"
