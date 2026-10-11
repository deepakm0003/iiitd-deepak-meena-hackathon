"""Uploaded text is analysed by the real pipeline code (fake models, no downloads) and never stored."""

from pathlib import Path

import pytest

from tripwire.analyze import Analyzer
from tripwire.nlp.classifier import ClassResult
from tripwire.nlp.engine import NlpEngine
from tripwire.nlp.linking import EntityLinker
from tripwire.nlp.sentiment import FinbertSentiment
from tripwire.scoring.impact import FACTORS, ImpactModel
from tripwire.stress.service import StressService
from tripwire.universe import load_universe

ROOT = Path(__file__).resolve().parents[1]


class FakeSentiment(FinbertSentiment):
    def __init__(self):
        super().__init__({"name": "fake-finbert"}, entity_model=Path("__none__"))

    def probabilities(self, texts):
        return [{"positive": 0.05, "negative": 0.9, "neutral": 0.05} for _ in texts]


class FakeEmbedder:
    name = "fake"

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


class FakeClassifier:
    method = "head"

    def predict(self, texts):
        return [ClassResult("Other", {"Other": 0.8}, 0.8, "head") for _ in texts]


@pytest.fixture
def analyzer(store):
    engine = NlpEngine(EntityLinker(load_universe()), classifier=FakeClassifier(), sentiment=FakeSentiment(),
                       embedder=FakeEmbedder())
    model = ImpactModel(weights=dict(zip(FACTORS, [0.25, 0.15, 0.15, 0.1, 0.1, 0.1, 0.15], strict=True)),
                        h_table={"Credit Event": 0.86, "__default__": 0.36},
                        calibration_adjusted=[i / 100 for i in range(100)],
                        calibration_period=("2023-01-01", "2025-06-30"))
    return Analyzer(store, StressService(store, ROOT / "data"), ROOT, engine=engine, model=model)


def test_upload_gets_the_full_trace_and_nothing_is_stored(analyzer, store):
    r = analyzer.analyse("JPMorgan Chase files for Chapter 11 bankruptcy protection",
                         "The bank said it filed a voluntary petition under Chapter 11 on Monday.")
    assert r["stored"] is False
    assert r["annotation"]["primary"] == "JPM" and r["annotation"]["event_type"] == "Credit Event"
    s = r["signal"]
    assert s["event_id"].startswith("upl_") and 1 <= s["impact_score"] <= 10
    assert s["impact_breakdown"]["factors"]["Q_source_credibility"] == 0.7  # general news tier
    assert r["decision"]["checks"]["stress_mappable"]["ok"]
    assert r["stress"]["trigger"] == "upload" and r["stress"]["pnl_total"] < 0 and "positions" not in r["stress"]
    # nothing reached the store: no annotation, signal or stress run
    assert store.get_annotations() == [] and store.count_signals() == 0 and store.list_stress_runs() == []


def test_text_with_no_subject_gives_no_signal_and_says_why(analyzer):
    r = analyzer.analyse("My favourite pasta recipe", "Boil water, add salt.")
    assert r["signal"] is None and r["stress"] is None and "No subject" in r["reason_no_signal"]


def test_batch_returns_one_row_per_item(analyzer):
    rows = analyzer.analyse_batch([("Apple sued by the DOJ over smartphone monopoly", ""), ("", "Lovely weather.")])
    assert [r["row"] for r in rows] == [1, 2]
    assert rows[0]["subject"] == "AAPL" and rows[0]["impact"] is not None
    assert rows[1]["impact"] is None and rows[1]["note"]
    with pytest.raises(ValueError):
        analyzer.analyse_batch([("x", "")] * 301)


def test_uploaded_portfolio_is_built_with_the_book_rules_and_validated():
    import json

    from tripwire.config import load_yaml
    from tripwire.portfolio.upload import build_uploaded_book

    market = json.loads((ROOT / "data" / "book.json").read_text(encoding="utf-8"))["market_snapshot"]
    universe = {c["ticker"]: c for c in load_yaml("universe.yaml")["companies"]}
    book = build_uploaded_book([
        {"type": "loan", "issuer": "jpm", "exposure": "5,000,000", "grade": "A"},
        {"type": "bond", "issuer": "BAC", "exposure": 2_000_000, "grade": "BBB", "maturity_years": 7},
        {"type": "equity", "issuer": "NVDA", "exposure": 1_000_000},
        {"type": "sme_loan", "issuer": "Corner Bakery", "exposure": 250_000, "grade": "BB",
         "sector": "Consumer Staples", "state": "ca"},
    ], market, universe)
    assert [p["type"] for p in book["tranche2"]] == ["corporate_loan", "bond", "equity"]
    assert book["tranche2"][0]["sector"] == "Financials" and book["tranche2"][0]["pd"] == 0.0005
    assert abs(book["tranche2"][1]["price"] - 1.0) < 1e-6  # no coupon given: priced at par
    assert book["tranche1"][0]["state"] == "CA" and book["capital"]["cet1_ratio"] == 0.12
    with pytest.raises(ValueError, match="row 1.*not a tracked ticker.*row 2.*exposure"):
        build_uploaded_book([{"type": "loan", "issuer": "NOPE", "exposure": 1},
                             {"type": "equity", "issuer": "AAPL", "exposure": "-5"}], market, universe)


def test_portfolio_analysis_runs_live_signals_against_the_uploaded_book(analyzer, store):
    r = analyzer.analyse_portfolio([{"type": "loan", "issuer": "JPM", "exposure": 5_000_000, "grade": "A"}])
    assert r["stored"] is False and r["portfolio"]["n_positions"] == {"tranche1": 0, "tranche2": 1}
    assert r["events"]["checked"] == 0  # the test store has no signals
    assert store.list_stress_runs() == []


def test_uploaded_sme_loans_get_a_watchlist_status_from_their_grade(analyzer):
    r = analyzer.analyse_portfolio([{"type": "sme_loan", "issuer": "Delhi Auto Parts", "exposure": 2_000_000,
                                     "grade": "B", "sector": "Consumer Discretionary"}])
    row = next(w for w in r["watchlist"]["names"] if w["name"] == "Delhi Auto Parts")
    assert row["drivers"][0]["source"] == "grade PD" and row["score"] > 0


def test_a_long_equity_never_loses_more_than_its_value(store):
    from tripwire.config import load_yaml
    from tripwire.portfolio.upload import build_uploaded_book

    universe = {c["ticker"]: c for c in load_yaml("universe.yaml")["companies"]}
    base = StressService(store, Path(__file__).resolve().parents[1] / "data")
    book = build_uploaded_book([{"type": "equity", "issuer": "TSLA", "exposure": 8_000_000}],
                               base.book["market_snapshot"], universe)
    svc = StressService(store, Path(__file__).resolve().parents[1] / "data", book=book)
    run = svc.run_custom("Credit Event", 10, entity="TSLA")
    assert run["pnl_total"] >= -8_000_000
    assert run["capital"]["cet1_ratio_after"] >= 0
