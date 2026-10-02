"""NLP engine wiring, with fake models (no downloads): which stage decides, primary entity, macro handling."""

from datetime import UTC, datetime

import pytest

from tripwire.models import Document
from tripwire.nlp.classifier import ClassResult
from tripwire.nlp.engine import NlpEngine
from tripwire.nlp.linking import EntityLinker
from tripwire.nlp.sentiment import FinbertSentiment
from tripwire.universe import load_universe


def _fake_probs(text):
    neg = any(w in text.lower() for w in ("loss", "falls", "misses", "bankrupt"))
    pos = any(w in text.lower() for w in ("beats", "record", "surges"))
    return {"positive": 0.9 if pos else 0.05, "negative": 0.9 if neg else 0.05,
            "neutral": 0.05 if (pos or neg) else 0.9}


class FakeSentiment(FinbertSentiment):
    """Real unit selection and aggregation; fake models. The fake pair model judges only the part of the
    sentence about the given entity (what the fine-tuned entity model learns to do)."""

    def __init__(self):
        super().__init__({"name": "fake-finbert"}, entity_model=__import__("pathlib").Path("__none__"))
        self._entity = type("FakeEntityModel", (), {"name": "fake-entity-model"})()  # pretend one is installed

    def probabilities(self, texts):
        return [_fake_probs(t) for t in texts]

    def pair_probabilities(self, texts, entities):
        out = []
        for text, entity in zip(texts, entities, strict=True):
            part = next((p for p in text.split(" while ") if entity in p), text)
            out.append(_fake_probs(part))
        return out


class FakeEmbedder:
    name = "fake-minilm"

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


class FakeClassifier:
    method = "head"

    def __init__(self):
        self.seen = []

    def predict(self, texts):
        self.seen += texts
        return [ClassResult("Other", {"Other": 0.7, "Earnings": 0.3}, 0.7, "head") for _ in texts]


def d(i, title, lead="", source="finnhub", hints=None):
    return Document(raw_id=i, dedup_key=f"k{i}", source=source, source_type="news", title=title, lead=lead,
                    published_at=datetime(2026, 10, 1, tzinfo=UTC), hints=hints or {})


@pytest.fixture
def engine():
    return NlpEngine(EntityLinker(load_universe()), classifier=FakeClassifier(), sentiment=FakeSentiment(),
                     embedder=FakeEmbedder())


def test_rules_decide_before_ml_and_ml_gets_only_the_rest(engine):
    docs = [d(1, "Regional lender files for Chapter 11 bankruptcy"), d(2, "Company hosts investor day")]
    a, b = engine.annotate(docs)
    assert (a.event_type, a.event_method) == ("Credit Event", "rule:bankruptcy")
    assert (b.event_type, b.event_method, b.event_confidence) == ("Other", "head", 0.7)
    assert engine.classifier.seen == ["Company hosts investor day"]


def test_entity_level_sentiment_separates_companies_in_one_headline(engine):
    [a] = engine.annotate([d(1, "Nike beats estimates while Ford posts surprise loss")])
    by_ticker = {e.ticker: e for e in a.entities}
    assert by_ticker["NKE"].sentiment > 0.5 and by_ticker["F"].sentiment < -0.5
    assert a.primary == "NKE" and a.sentiment == by_ticker["NKE"].sentiment


def test_earnings_label_needs_earnings_evidence():
    from tripwire.nlp.engine import _guard_earnings

    pred = ClassResult("Earnings", {"Earnings": 0.6, "Other": 0.3, "Merger/Acquisition": 0.1}, 0.6, "head")
    fixed = _guard_earnings(pred, "Boeing wins $20 billion Navy fighter contract")
    assert (fixed.event_type, fixed.method, fixed.confidence) == ("Other", "head+guard", 0.3)
    assert _guard_earnings(pred, "Nike beats estimates as quarterly revenue rises").event_type == "Earnings"


def test_macro_items_use_document_sentiment(engine):
    [a] = engine.annotate([d(1, "RBI holds repo rate as inflation falls", source="rbi")])
    assert a.primary == "MACRO" and a.event_type == "Macroeconomic"
    assert a.sentiment_method == "document"


def test_filings_are_classified_by_item_and_linked_to_filer(engine):
    doc = d(1, "JPMORGAN CHASE & CO files 8-K: Item 2.02 Results", source="edgar",
            hints={"ticker": "JPM", "items": ["2.02", "9.01"]})
    [a] = engine.annotate([doc])
    assert (a.primary, a.event_type, a.event_method) == ("JPM", "Earnings", "8k_item:2.02")
    assert a.entities[0].link_confidence == 1.0


def test_filing_sentiment_reads_the_press_release_not_the_template(engine):
    doc = d(1, "ACME CORP files 8-K: Item 2.02 Results", source="edgar",
            lead="The Company reported a net loss of $2 billion. Revenue falls sharply.",
            hints={"ticker": "JPM", "items": ["2.02"]})
    [a] = engine.annotate([doc])
    assert a.sentiment < -0.5
    assert all(e["location"] == "lead" for e in a.sentiment_evidence)


def test_annotation_round_trips_through_the_store(engine, store, make_doc):
    raw_id = store.add_raw(make_doc(title="Nike beats estimates"))
    from tripwire.ingestion.normalize import normalize

    store.add_document(normalize(raw_id, store.get_raw(raw_id)))
    assert [doc.raw_id for doc in store.documents_without_annotation()] == [raw_id]
    store.add_annotations(engine.annotate(store.documents_without_annotation()))
    assert store.documents_without_annotation() == []
    [saved] = store.get_annotations()
    assert saved["primary"] == "NKE" and saved["embedding"] == [1.0, 0.0]


def test_ml_macro_guess_without_evidence_is_none(engine):
    # Real case: a local GDELT story labelled natural-disaster by the ML layer was scored as a market-wide event.
    class DisasterClassifier(FakeClassifier):
        def predict(self, texts):
            return [ClassResult("Natural Disaster/Supply Chain", {"Natural Disaster/Supply Chain": 0.6}, 0.6, "head")
                    for _ in texts]

    engine.classifier = DisasterClassifier()
    [local] = engine.annotate([d(1, "List of Maine restaurants that closed in September", source="gdelt")])
    assert local.primary == "NONE" and local.macro_evidence == 0.0
    fed_doc = d(2, "Officials discuss outlook", source="gdelt", hints={"macro_orgs": ["Federal Reserve"]})
    [fed] = engine.annotate([fed_doc])
    assert fed.primary == "MACRO" and fed.macro_evidence == 0.9
