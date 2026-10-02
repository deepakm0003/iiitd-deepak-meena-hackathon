"""Module B end to end: trigger decisions, automatic runs, watchlist and the API, on a small hand-built book."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from test_stress import ANALOGS, CFG, book
from tripwire.api.app import create_app
from tripwire.stress.service import StressService
from tripwire.stress.trigger import decide

NOW = datetime.now(UTC).replace(microsecond=0)
TRIGGER = {"direct_large_share": 0.02, "direct_large": 5.5, "direct_any": 6.0, "indirect_share": 0.10,
           "indirect": 6.5, "market_only": 7.0, "auto_max_age_days": 7}


def signal(event_id="ev1", entity="KEY", impact=6.0, sentiment=-0.6, factuality="confirmed", method="head+zs",
           event_type="Credit Event", subtype=None, sector="Financials", days_ago=0.5):
    return {
        "event_id": event_id, "primary_entity": entity, "event_type": event_type, "event_subtype": subtype,
        "event_method": method, "impact_score": impact, "sentiment_score": sentiment,
        "sentiment_label": "negative" if sentiment < -0.15 else "positive" if sentiment > 0.15 else "neutral",
        "risk_level": "High", "factuality": factuality, "frame": {"places": []}, "p_large_move": 0.4,
        "company": {"ticker": entity, "sector": sector} if entity != "MACRO" else None,
        "headline": f"{entity} story", "first_seen_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


@pytest.fixture
def service(store, tmp_path, monkeypatch):
    b = book()
    b.update({"as_of": "2026-10-01", "totals": {}, "capital": {**b["capital"], "cet1_ratio": 0.125}})
    (tmp_path / "book.json").write_text(json.dumps(b), encoding="utf-8")
    (tmp_path / "market_inputs.json").write_text(json.dumps({"analogs": ANALOGS, "betas": {}}), encoding="utf-8")
    svc = StressService(store, tmp_path)
    svc.engine.grades, svc.trigger_cfg = CFG["grades"], TRIGGER
    return svc


def test_trigger_lowers_the_bar_for_names_the_book_lends_to(service):
    direct = decide(signal(impact=5.8), service.book, service.shocks, TRIGGER)
    assert direct["trigger"] and direct["threshold"] == 5.5          # KEY: bond + loan, > 2% of the book
    unrelated = decide(signal(entity="MSFT", sector="Information Technology", impact=6.5), service.book,
                       service.shocks, TRIGGER)
    assert not unrelated["trigger"] and unrelated["threshold"] == 7.0
    assert unrelated["checks"]["severe_enough"]["ok"] is False


@pytest.mark.parametrize("change, failing", [
    ({"factuality": "rumour"}, "factual"),
    ({"sentiment": 0.7}, "adverse"),
    ({"event_type": "Earnings"}, "stress_mappable"),
])
def test_trigger_rejects_talk_good_news_and_unmappable_classes(service, change, failing):
    d = decide(signal(**change), service.book, service.shocks, TRIGGER)
    assert not d["trigger"] and d["checks"][failing]["ok"] is False


def test_a_bankruptcy_filing_by_a_borrower_triggers_whatever_its_impact(service):
    s = signal(impact=3.0, sentiment=0.1, method="8k_item:1.03", subtype="bankruptcy")
    d = decide(s, service.book, service.shocks, TRIGGER)
    assert d["trigger"] and "1.03" in d["hard_flags"]


def test_automatic_runs_happen_once_per_event_unless_impact_moves(service, store):
    store.upsert_signals([signal()])
    assert len(service.auto([signal()])) == 1
    assert service.auto([signal()]) == []                            # same event, same Impact: no rerun
    assert len(service.auto([signal(impact=6.6)])) == 1              # Impact moved by >= 0.5: rerun
    assert service.auto([signal(event_id="old", days_ago=30)]) == []  # stale signals are not auto-run
    runs = store.list_stress_runs()
    assert len(runs) == 2 and all(r["trigger"] == "auto" for r in runs)


def test_watchlist_flags_a_borrower_with_a_bankruptcy_filing_red(service):
    w = service.watchlist([signal(method="8k_item:1.03", subtype="bankruptcy"), signal("ev2", entity="XOM",
                           sector="Energy", sentiment=0.6)])
    rows = {r["name"]: r for r in w["names"]}
    assert rows["KEY"]["status"] == "Red" and "1.03" in rows["KEY"]["hard_flags"]
    assert rows["XOM"]["status"] == "Green"                          # good news is not a warning
    assert sum(w["counts"].values()) == len(w["names"])


def test_stress_api_end_to_end(service, store):
    store.upsert_signals([signal()])
    client = TestClient(create_app(store, service))
    assert client.get("/portfolio").json()["n_positions"]["tranche1"] == 3
    assert client.get("/signals/ev1/stress-decision").json()["trigger"] is True
    run = client.post("/stress-test", json={"event_id": "ev1"}).json()
    assert run["trigger"] == "manual" and run["pnl_total"] < 0
    assert set(run["reverse_stress"]) == {"basel", "rbi"}
    assert client.get(f"/stress-test/{run['run_id']}").json()["run_id"] == run["run_id"]
    what_if = client.post("/stress-test", json={"event_type": "Natural Disaster/Supply Chain", "impact": 9,
                                                "states": ["fl"]}).json()
    assert what_if["trigger"] == "what-if"
    hit = {r["id"] for r in what_if["positions"] if r["paths"]}
    assert "L1" in hit and "L2" not in hit                           # FL obligor hit, CA obligor not
    assert [r["trigger"] for r in client.get("/stress-runs").json()] == ["what-if", "manual"]
    assert client.post("/stress-test", json={"event_type": "Earnings", "impact": 8}).status_code == 422
    assert client.post("/stress-test", json={"event_id": "nope"}).status_code == 404
    assert client.get("/watchlist?status=Red").status_code == 200


def test_a_state_named_in_a_macro_story_does_not_lower_the_bar(service):
    s = signal(entity="MACRO", event_type="Macroeconomic", impact=6.7, sector=None)
    s["frame"]["places"] = ["Florida, United States"]   # the test book has an obligor in FL
    d = decide(s, service.book, service.shocks, TRIGGER)
    assert d["exposure"]["geography"] == 0 and d["threshold"] == 7.0 and not d["trigger"]


def test_an_event_adverse_by_nature_triggers_despite_reassuring_tone(service):
    s = signal(impact=7.5, sentiment=0.86, method="rule:bank_run", subtype="liquidity_stress")
    d = decide(s, service.book, service.shocks, TRIGGER)
    assert d["trigger"] and "adverse by nature" in d["checks"]["adverse"]["detail"]


def test_trace_links_signal_to_capital_and_runs_carry_a_sensitivity_range(service, store):
    store.upsert_signals([signal()])
    client = TestClient(create_app(store, service))
    before = client.get("/signals/ev1/trace").json()
    assert before["what_happens_to_the_bank"] is None and before["stress_available"] is True
    assert before["why_it_matters_to_this_book"]["trigger"] is True
    run = client.post("/stress-test", json={"event_id": "ev1"}).json()
    sens = run["sensitivity"]
    assert sens["mild"]["pnl_total"] >= sens["base"]["pnl_total"] >= sens["severe"]["pnl_total"]
    after = client.get("/signals/ev1/trace").json()["what_happens_to_the_bank"]
    assert after["run_id"] == run["run_id"] and after["capital"]["delta"]["cet1"] < 0


def test_one_local_flood_story_does_not_put_a_states_smes_on_the_watchlist(service):
    local = signal("flood", entity="MACRO", event_type="Natural Disaster/Supply Chain", sector=None, impact=6.0)
    local["frame"]["places"] = ["Tampa, Florida, United States"]
    local["corroboration"] = {"n_publishers": 1}
    rows = {r["positions"][0]: r for r in service.watchlist([local])["names"]}
    assert len(rows["L1"]["drivers"]) == 1                      # only the behavioural model
    big = {**local, "corroboration": {"n_publishers": 12}}
    rows = {r["positions"][0]: r for r in service.watchlist([big])["names"]}
    assert rows["L1"]["drivers"][1]["source"] == "event in home state"
