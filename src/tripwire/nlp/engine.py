"""The per-document NLP pipeline: link -> classify (items, rules, ML) -> sentiment -> frame -> embedding.

Batch-oriented so GPU/CPU forward passes are shared across documents. Output is one Annotation per document,
stored in doc_annotations; clustering, novelty and the Impact Score (later stages) read from there.
Every stage records how it decided (method + confidence + evidence) for the dashboard's "why" view.
"""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from tripwire.models import Document
from tripwire.nlp.classifier import ClassResult, EventClassifier
from tripwire.nlp.embeddings import Embedder
from tripwire.nlp.events import EventRules
from tripwire.nlp.frame import extract_frame
from tripwire.nlp.linking import EntityLinker, LinkedEntity
from tripwire.nlp.ner import enrich_frame
from tripwire.nlp.sentiment import FinbertSentiment

PRIMARY_MIN_RELEVANCE = 0.35  # below this an entity is a passing mention, not the subject (A-17)
MACRO_SOURCES = {"rbi", "fed"}
MACRO_RULES = {"central_bank", "macro_data", "sanctions", "tariffs", "conflict", "disaster", "supply"}
STRONG_FINANCE_THEMES = {"ECON_BANKRUPTCY", "ECON_CENTRALBANK", "WB_1235_CENTRAL_BANKS", "ECON_INTEREST_RATES",
                         "ECON_SOVEREIGN_DEBT", "ECON_INFLATION", "ECON_STOCKMARKET"}
MIN_MACRO_EVIDENCE = 0.6
MAX_ENTITIES_SCORED = 3


def macro_evidence(doc: Document, event_method: str) -> float:
    """How strongly the item is about the economy or markets as a whole (0-1).

    Found on live data: local GDELT stories (restaurant closures, a rural fire district) were labelled
    natural-disaster/macro by the ML layer and then scored as market-wide events. Market-wide status now
    needs evidence; an ML label alone is not enough.
    """
    if doc.source in MACRO_SOURCES:
        return 1.0
    if doc.hints.get("macro_orgs"):
        return 0.9
    if event_method.startswith("rule:") and event_method.split(":", 1)[1] in MACRO_RULES:
        return 0.8
    if len(set(doc.hints.get("themes", [])) & STRONG_FINANCE_THEMES) >= 1:
        # GDELT theme tags alone are noisy (page footers, tickers): they get a page collected, but are not
        # enough to make it market-wide. Found on live data: lighthouse and lawn-care pages tagged ECON_*.
        return 0.4
    return 0.0


EARNINGS_CUES = re.compile(
    r"\b(earnings|results|quarter(ly)?|q[1-4]|fiscal|revenues?|sales|profits?|loss(es)?|eps|per share|"
    r"guidance|outlook|forecast|beats?|miss(es|ed)?|estimates)\b",
    re.IGNORECASE,
)


def _guard_earnings(result: ClassResult, text: str) -> ClassResult:
    """An ML 'Earnings' label needs at least one earnings word; otherwise use the next most likely class.

    Found on live data: contract wins and industry awards were labelled Earnings, and because earnings
    filings have the strongest measured market reaction, those errors inflated Impact.
    """
    if result.event_type != "Earnings" or EARNINGS_CUES.search(text) or not result.probabilities:
        return result
    ranked = sorted((p, c) for c, p in result.probabilities.items() if c != "Earnings")
    if not ranked:
        return result
    prob, cls = ranked[-1]
    return ClassResult(cls, result.probabilities, round(prob, 4), f"{result.method}+guard")


class EntityAnnotation(BaseModel):
    ticker: str
    cik: int | None
    sector: str
    link_confidence: float
    relevance: float
    in_title: bool
    method: str
    sentiment: float | None = None
    sentiment_label: str | None = None


class Annotation(BaseModel):
    raw_id: int
    dedup_key: str
    source: str
    source_type: str
    published_at: datetime
    primary: str                        # ticker | MACRO | NONE
    entities: list[EntityAnnotation]
    event_type: str
    event_subtype: str | None
    event_method: str                   # 8k_item:x | rule:x | head | setfit | zero_shot
    event_confidence: float
    event_probabilities: dict[str, float] = Field(default_factory=dict)
    sentiment: float
    sentiment_label: str
    sentiment_method: str
    sentiment_evidence: list[dict[str, Any]] = Field(default_factory=list)
    frame: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] = Field(default_factory=list)
    model_versions: dict[str, str | None] = Field(default_factory=dict)
    macro_evidence: float = 0.0          # 0-1, how market-wide the item is (relevance for MACRO events)
    annotated_at: datetime


class NlpEngine:
    def __init__(
        self,
        linker: EntityLinker,
        rules: EventRules | None = None,
        classifier: EventClassifier | None = None,
        sentiment: FinbertSentiment | None = None,
        embedder: Embedder | None = None,
        ner=None,
    ) -> None:
        self.linker = linker
        self.rules = rules or EventRules()
        self.classifier = classifier or EventClassifier()
        self.sentiment = sentiment or FinbertSentiment()
        self.embedder = embedder or Embedder()
        self.ner = ner  # optional GlinerNer: enriches frame slots (targets, authorities, places, amounts)

    def annotate(self, docs: list[Document]) -> list[Annotation]:
        if not docs:
            return []
        texts = [f"{d.title}. {d.lead}".strip() if d.lead else d.title for d in docs]
        linked = [self.linker.link(d) for d in docs]
        decisions = [self.rules.decide(self.rules.evidence(d)) for d in docs]
        undecided = [i for i, dec in enumerate(decisions) if dec is None]
        ml = dict(zip(undecided, self.classifier.predict([texts[i] for i in undecided]), strict=True))
        embeddings = self.embedder.encode(texts)
        spans = self.ner.extract(texts) if self.ner else [[] for _ in docs]
        now = datetime.now(UTC)
        out = []
        for i, (doc, entities) in enumerate(zip(docs, linked, strict=True)):
            if decisions[i]:
                event_type, subtype = decisions[i].event_type, decisions[i].subtype
                method, confidence, probs = decisions[i].source, decisions[i].confidence, {}
            else:
                result = _guard_earnings(ml[i], texts[i])
                event_type, subtype, method = result.event_type, None, result.method
                confidence, probs = result.confidence, result.probabilities
            macro = macro_evidence(doc, method)
            primary = self._primary(doc, entities, macro)
            scored = entities[:MAX_ENTITIES_SCORED]
            sentiments = self.sentiment.for_entities(doc, scored)
            main = sentiments[primary.ticker if isinstance(primary, LinkedEntity) and primary.ticker in sentiments
                              else "MACRO"]
            out.append(
                Annotation(
                    raw_id=doc.raw_id,
                    dedup_key=doc.dedup_key,
                    source=doc.source,
                    source_type=doc.source_type,
                    published_at=doc.published_at,
                    primary=primary.ticker if isinstance(primary, LinkedEntity) else primary,
                    entities=[
                        EntityAnnotation(
                            ticker=e.ticker, cik=e.cik, sector=e.sector, link_confidence=e.link_confidence,
                            relevance=e.relevance, in_title=e.in_title, method=e.method,
                            sentiment=sentiments[e.ticker].score if e.ticker in sentiments else None,
                            sentiment_label=sentiments[e.ticker].label if e.ticker in sentiments else None,
                        )
                        for e in entities
                    ],
                    event_type=event_type,
                    event_subtype=subtype,
                    event_method=method,
                    event_confidence=confidence,
                    event_probabilities=probs,
                    sentiment=main.score,
                    sentiment_label=main.label,
                    sentiment_method=main.method,
                    sentiment_evidence=main.evidence,
                    frame=self._frame(doc, primary, spans[i]),
                    embedding=embeddings[i],
                    model_versions={
                        "sentiment": self.sentiment.entity_model or self.sentiment.name,
                        "ner": self.ner.name if self.ner else None,
                        "embedding": self.embedder.name,
                        "event_classifier": self.classifier.method if not decisions[i] else "rules",
                    },
                    macro_evidence=macro,
                    annotated_at=now,
                )
            )
        return out

    @staticmethod
    def _frame(doc: Document, primary: LinkedEntity | str, spans: list) -> dict:
        actor = primary.ticker if isinstance(primary, LinkedEntity) else None
        places = [loc["name"] for loc in doc.hints.get("locations", [])]
        frame = extract_frame(doc.title, doc.lead, actor, places).as_dict()
        return enrich_frame(frame, spans) if spans else frame

    def _primary(self, doc: Document, entities: list[LinkedEntity], macro: float) -> LinkedEntity | str:
        """The subject: a company that is central to the text, else MACRO if there is market-wide evidence,
        else NONE (passing mentions and unsupported macro guesses produce no signal)."""
        if entities and entities[0].relevance >= PRIMARY_MIN_RELEVANCE:
            return entities[0]
        if macro >= MIN_MACRO_EVIDENCE:
            return "MACRO"
        return "NONE"
