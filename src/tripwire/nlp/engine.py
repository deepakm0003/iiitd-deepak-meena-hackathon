"""The per-document NLP pipeline: link -> classify (items, rules, ML) -> sentiment -> frame -> embedding.

Batch-oriented so GPU/CPU forward passes are shared across documents. Output is one Annotation per document,
stored in doc_annotations; clustering, novelty and the Impact Score (later stages) read from there.
Every stage records how it decided (method + confidence + evidence) for the dashboard's "why" view.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from tripwire.models import Document
from tripwire.nlp.classifier import EventClassifier
from tripwire.nlp.embeddings import Embedder
from tripwire.nlp.events import EventRules
from tripwire.nlp.frame import extract_frame
from tripwire.nlp.linking import EntityLinker, LinkedEntity
from tripwire.nlp.ner import enrich_frame
from tripwire.nlp.sentiment import FinbertSentiment

PRIMARY_MIN_RELEVANCE = 0.35  # below this an entity is a passing mention, not the subject (A-17)
MACRO_SOURCES = {"rbi", "fed"}
MACRO_CLASSES = {"Macroeconomic", "Geopolitical", "Natural Disaster/Supply Chain"}
MAX_ENTITIES_SCORED = 3


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
                result = ml[i]
                event_type, subtype, method = result.event_type, None, result.method
                confidence, probs = result.confidence, result.probabilities
            primary = self._primary(doc, entities, event_type)
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

    def _primary(self, doc: Document, entities: list[LinkedEntity], event_type: str) -> LinkedEntity | str:
        if entities and entities[0].relevance >= PRIMARY_MIN_RELEVANCE:
            return entities[0]
        if doc.source in MACRO_SOURCES or doc.hints.get("macro_orgs") or event_type in MACRO_CLASSES:
            return "MACRO"
        return entities[0] if entities else "NONE"
