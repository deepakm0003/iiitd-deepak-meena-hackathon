"""Golden replay: Western Alliance, 13 March 2023 (the SVB crisis), through the whole chain.

source document -> entity -> event -> factuality -> (sentiment) -> Impact -> exposure and trigger -> shocks
-> position P&L -> ECL -> RWA -> CET1. The source document is the real 8-K (OBSERVED, public); the book and
shock sizes are the repository's (SYNTHETIC / ASSUMPTION / HISTORICAL as labelled). Expected values are
derived from config wherever possible; the recorded fixture (scripts/make_golden.py) anchors the outputs
that are results, so a change to NLP, scoring or the book that moves them fails here and must be reviewed.
"""

import json
from pathlib import Path

import pytest

from tripwire.config import load_yaml
from tripwire.models import Document
from tripwire.nlp.events import EventRules
from tripwire.nlp.frame import extract_frame
from tripwire.nlp.linking import EntityLinker
from tripwire.scoring.impact import ImpactModel
from tripwire.settings import ROOT
from tripwire.stress.engine import StressEngine, severity_k
from tripwire.stress.trigger import decide, position_exposure, scenario_from_signal
from tripwire.universe import load_universe

FIXTURE = json.loads((Path(__file__).parent / "western_alliance.json").read_text(encoding="utf-8"))
BOOK = json.loads((ROOT / "data" / "book.json").read_text(encoding="utf-8"))
MARKET = json.loads((ROOT / "data" / "market_inputs.json").read_text(encoding="utf-8"))
SHOCKS = load_yaml("shocks.yaml")
CFG = load_yaml("book.yaml")


@pytest.fixture(scope="module")
def doc():
    return Document(**FIXTURE["document"])


@pytest.fixture(scope="module")
def result():
    signal = FIXTURE["signal"]
    engine = StressEngine(BOOK, MARKET, CFG)
    return engine.run(scenario_from_signal(signal, MARKET["analogs"], SHOCKS))


# ---- NLP: document -> entity -> event ---------------------------------------------------------------
def test_entity_is_the_filer(doc):
    linked = EntityLinker(load_universe()).link(doc)
    assert linked and linked[0].ticker == "WAL" and linked[0].link_confidence >= 0.95


def test_event_is_a_liquidity_credit_event_from_a_deterministic_rule(doc):
    rules = EventRules()
    decision = rules.decide(rules.evidence(doc))
    assert (decision.event_type, decision.subtype, decision.source) == ("Credit Event", "liquidity_stress",
                                                                        "rule:bank_run")
    assert FIXTURE["annotation"]["event_method"] == decision.source   # the stored annotation agrees


def test_the_statement_is_a_fact_not_a_rumour(doc):
    assert extract_frame(doc.title, doc.lead, "WAL").factuality == "confirmed"


@pytest.mark.skipif(not (ROOT / "models" / "sentiment_entity").exists(), reason="entity sentiment model not present")
def test_entity_sentiment_reproduces(doc):
    from tripwire.nlp.sentiment import FinbertSentiment

    # The recorded run used the first training of the entity-sentiment model (GPU server, +0.86). The published
    # weights (release models-v1, retrained 2026-10-10 with the same data, split and settings; same test macro-F1
    # 0.888) score this sentence +0.56. Both read the bank's own statement as positive, which is the point of the
    # case: the event is adverse by nature even though the tone is reassuring. Impact and stress in the fixture
    # come from the recorded run (docs/IMPROVEMENT_LOG.md).
    known = {"recorded run": FIXTURE["annotation"]["sentiment"], "models-v1": 0.5556}
    linked = EntityLinker(load_universe()).link(doc)
    score = FinbertSentiment().for_entities(doc, linked[:1])["WAL"].score
    assert any(score == pytest.approx(v, abs=0.02) for v in known.values()), (score, known)
    assert score > 0


# ---- Impact -------------------------------------------------------------------------------------------
def test_impact_is_reproduced_by_the_committed_model_from_consistent_factors():
    model = ImpactModel.load(ROOT / "models" / "impact_model.json")
    breakdown = FIXTURE["signal"]["impact_breakdown"]
    factors = breakdown["factors"]
    assert factors["S_severity"] == EventRules().prior("Credit Event", "liquidity_stress")    # from taxonomy
    assert factors["H_historical_reaction"] == pytest.approx(model.h_table["Credit Event"], abs=1e-4)
    assert factors["M_sentiment_magnitude"] == pytest.approx(abs(FIXTURE["annotation"]["sentiment"]), abs=1e-4)
    relevance = (breakdown["relevance_gate"] - model.gate_floor) / model.gate_slope
    scored = model.score(factors, relevance)
    assert scored["impact"] == pytest.approx(FIXTURE["signal"]["impact_score"], abs=0.01)
    assert scored["p_large_move"] == FIXTURE["signal"]["p_large_move"]


# ---- exposure and trigger ----------------------------------------------------------------------------
def test_trigger_fires_through_direct_exposure_and_adverse_nature():
    d = decide(FIXTURE["signal"], BOOK, SHOCKS, CFG["stress_trigger"])
    positions = BOOK["tranche1"] + BOOK["tranche2"]
    share = sum(position_exposure(p) for p in positions if p.get("issuer") == "WAL") / sum(
        position_exposure(p) for p in positions)
    assert d["exposure"]["direct"] == pytest.approx(share, abs=1e-5)
    assert 0 < share < CFG["stress_trigger"]["direct_large_share"]
    assert d["threshold"] == CFG["stress_trigger"]["direct_any"]
    assert d["trigger"] and "adverse by nature" in d["checks"]["adverse"]["detail"]   # tone is +0.86


# ---- shocks, P&L, ECL, RWA, CET1 ----------------------------------------------------------------------
def test_severity_and_shock_provenance(result):
    k = severity_k(FIXTURE["signal"]["impact_score"])
    assert result["scenario"]["k"] == k
    analog = MARKET["analogs"]["Credit Event"]
    systemic = result["scenario"]["layers"]["systemic"]
    assert systemic["rate_10y_bp"]["value"] == analog["rate_10y_bp"]           # measured SVB window
    assert systemic["rate_10y_bp"]["source"].startswith("MEASURED")


def test_the_borrower_loan_takes_the_direct_pd_shock_and_migrates_a_grade(result):
    loan = next(r for r in result["positions"] if r["id"] == "LOAN-WAL")
    path = loan["paths"][0]
    m = SHOCKS["classes"]["Credit Event"]["entity"]["pd_mult"]
    assert path["channel"] == "direct" and path["shock"] == pytest.approx(1 + result["scenario"]["k"] * (m - 1), 1e-4)
    pos = next(p for p in BOOK["tranche2"] if p["id"] == "LOAN-WAL")
    stressed_pd = pos["pd"] * path["shock"]
    stage2 = stressed_pd >= 3 * pos["pd_origination"] or stressed_pd >= 0.20
    assert loan["stage_after"] == (2 if stage2 else 1)
    grades = CFG["grades"]
    weight_change = grades[loan["grade_after"]]["risk_weight"] - grades[pos["grade"]]["risk_weight"]
    expected_rwa_change = pos["ead"] * weight_change
    assert loan["rwa_after"] - loan["rwa_before"] == pytest.approx(expected_rwa_change, abs=1)
    assert loan["ecl_change"] == pytest.approx(-loan["dv"], abs=0.01)


def test_capital_reconciles(result):
    cap = result["capital"]
    tax = BOOK["capital"]["tax_rate"]
    assert cap["rwa_before"] == pytest.approx(BOOK["capital"]["rwa"], abs=1)      # engine RWA = book RWA
    assert cap["cet1_ratio_before"] == pytest.approx(cap["cet1_before"] / cap["rwa_before"], abs=1e-5)
    assert cap["cet1_ratio_after"] == pytest.approx(cap["cet1_after"] / cap["rwa_after"], abs=1e-5)
    assert cap["delta"]["cet1"] == pytest.approx(result["pnl_total"] * (1 - tax), abs=1)
    rec = cap["reconciliation"]
    assert cap["delta"]["rwa"] == pytest.approx(rec["rwa_change_from_rating_migration"]
                                                + rec["rwa_change_from_market_values"], abs=1)


def test_smes_are_not_reached_by_sector_contagion_and_every_zero_is_explained(result):
    smes = [r for r in result["positions"] if r["type"] == "sme_loan"]
    assert all(not r["paths"] for r in smes)
    fin = [r for r in smes if r["sector"] == "Financials"]
    assert fin and all("A-25" in r["unaffected_reason"] for r in fin)


def test_outputs_match_the_recorded_golden_run(result):
    recorded = FIXTURE["stress"]
    assert result["pnl_total"] == pytest.approx(recorded["pnl_total"], abs=1)
    assert result["ecl_change"] == pytest.approx(recorded["ecl_change"], abs=1)
    assert result["capital"]["cet1_ratio_after"] == pytest.approx(recorded["capital"]["cet1_ratio_after"], abs=1e-5)
    assert result["n_positions_affected"] == recorded["n_positions_affected"]
