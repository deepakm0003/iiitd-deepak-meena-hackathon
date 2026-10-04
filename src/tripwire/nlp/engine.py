"""The per-document NLP pipeline: link -> classify (items, rules, ML) -> sentiment -> frame -> embedding.

Batch-oriented so GPU/CPU forward passes are shared across documents. Output is one Annotation per document,
stored in doc_annotations; clustering, novelty and the Impact Score (later stages) read from there.
Every stage records how it decided (method + confidence + evidence) for the dashboard's "why" view.
"""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from tripwire.config import load_yaml
from tripwire.models import Document
from tripwire.nlp.classifier import ClassResult, EventClassifier
from tripwire.nlp.embeddings import Embedder
from tripwire.nlp.events import EventRules
from tripwire.nlp.frame import extract_frame
from tripwire.nlp.linking import EntityLinker, LinkedEntity
from tripwire.nlp.ner import enrich_frame
from tripwire.nlp.sentiment import FinbertSentiment

# Below this an entity is a passing mention, not the subject (A-17). 0.35 -> 0.60 on the gold dev split (silver
# labels): entity accuracy 0.702 -> 0.750; passing mentions ("pasta sold at Walmart", "a lease at Google's center")
# sat at relevance 0.49-0.57. 0.65 and above lose real subjects (0.679).
PRIMARY_MIN_RELEVANCE = 0.55  # 0.60 -> 0.55 on 478 human labels (round 3): late in-title subjects
MACRO_SOURCES = {"rbi", "fed"}
MACRO_RULES = {"central_bank", "macro_data", "macro_markets", "sanctions", "tariffs", "conflict", "disaster", "supply"}
MARKET_WIDE_CLASSES = {"Macroeconomic", "Geopolitical"}
# "Wells Fargo Downgrades Liquidia": the broker named before the rating verb is the actor, not the subject.
ANALYST_ACTION = re.compile(r"^\s*[\w&.,' ]{2,40}?\s+(downgrades|upgrades|initiates|reiterates|raises|cuts|lowers|"
                            r"boosts|maintains|resumes)\b", re.IGNORECASE)
STRONG_FINANCE_THEMES = {"ECON_BANKRUPTCY", "ECON_CENTRALBANK", "WB_1235_CENTRAL_BANKS", "ECON_INTEREST_RATES",
                         "ECON_SOVEREIGN_DEBT", "ECON_INFLATION", "ECON_STOCKMARKET"}
MIN_MACRO_EVIDENCE = 0.6
MAX_ENTITIES_SCORED = 3
MIN_FILING_TEXT = 80  # same minimum as the 8-K training examples


def macro_evidence(doc: Document, event_method: str, event_type: str | None = None) -> float:
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
    if event_type in MARKET_WIDE_CLASSES:
        # A Macroeconomic / Geopolitical label that reached this point came from a rule or passed the independent
        # zero-shot verifier: enough to be market-wide, at the minimum strength (round 3, 478 human labels:
        # 46 macro items had no subject at all).
        return MIN_MACRO_EVIDENCE
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


def _select(result: ClassResult, verifier: ClassResult | None, policy: dict) -> ClassResult:
    """Selective classification (docs/results/event_selective.json): abstain to Other when the head is unsure,
    and for stress-mappable classes when the independent zero-shot verifier does not support the label."""
    if result.event_type == "Other":
        return result
    floor = max(policy["min_confidence"], policy.get("min_confidence_by_class", {}).get(result.event_type, 0.0))
    if result.confidence < floor:
        return ClassResult("Other", result.probabilities, result.confidence, f"{result.method}:abstain")
    if result.event_type in policy["verify_classes"] and verifier is not None:
        support = verifier.probabilities.get(result.event_type, 0.0)
        if support < policy.get("verifier_min_p_by_class", {}).get(result.event_type, policy["verifier_min_p"]):
            return ClassResult("Other", result.probabilities, result.confidence, f"{result.method}:unverified")
        return ClassResult(result.event_type, result.probabilities, result.confidence, f"{result.method}+zs")
    return result


def classifier_text(doc: Document) -> str:
    """What the event classifier reads. 8-K filings: the press-release lead only, as in training (the templated
    title "files 8-K: Item 7.01 Regulation FD Disclosure" pulled filings toward Regulatory/Legal)."""
    if doc.source == "edgar":
        return doc.lead if len(doc.lead or "") >= MIN_FILING_TEXT else ""
    return f"{doc.title}. {doc.lead}".strip() if doc.lead else doc.title


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
    # Why the event label was chosen: the exact source text that fired a rule or 8-K item, or for an ML label the
    # source sentence the head scores highest for that class. Never generated text.
    event_evidence: dict[str, Any] = Field(default_factory=dict)
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
        cfg = load_yaml("models.yaml")["event_classifier"]
        self.selection = {"min_confidence": cfg.get("min_confidence", 0.0),
                          "min_confidence_by_class": cfg.get("min_confidence_by_class", {}),
                          "verify_classes": set(cfg.get("verify", {}).get("classes", [])),
                          "verifier_min_p": cfg.get("verify", {}).get("min_p", 0.0),
                          "verifier_min_p_by_class": cfg.get("verify", {}).get("min_p_by_class", {})}

    def _classify(self, texts: list[str], undecided: list[int]) -> dict[int, ClassResult]:
        """ML layer for items the 8-K map and rules left undecided, with the selective-classification policy."""
        empty = [i for i in undecided if not texts[i]]
        todo = [i for i in undecided if texts[i]]
        results = {i: _guard_earnings(r, texts[i])
                   for i, r in zip(todo, self.classifier.predict([texts[i] for i in todo]), strict=True)}
        verify = [i for i, r in results.items() if r.event_type in self.selection["verify_classes"]
                  and r.confidence >= self.selection["min_confidence"]]
        zero_shot = getattr(self.classifier, "predict_zero_shot", None)
        checks = dict(zip(verify, zero_shot([texts[i] for i in verify]), strict=True)) if verify and zero_shot \
            else {}
        out = {i: _select(r, checks.get(i), self.selection) for i, r in results.items()}
        out.update({i: ClassResult("Other", {}, 0.0, "8k:no_text") for i in empty})
        return out

    def _ml_evidence(self, texts: list[str], ml: dict[int, ClassResult]) -> dict[int, dict[str, Any]]:
        """For each ML label, the source sentence the head scores highest for that class (one batched pass)."""
        from tripwire.nlp.text import split_sentences

        out: dict[int, dict[str, Any]] = {}
        jobs: list[tuple[int, str]] = []
        for i, r in ml.items():
            if r.event_type == "Other":
                out[i] = {"source": r.method, "phrase": "", "context": "",
                          "note": "no class supported strongly enough; labelled Other"}
                continue
            sentences = [s for s in split_sentences(texts[i]) if len(s) > 15] or [texts[i]]
            jobs += [(i, s) for s in sentences[:8]]
        if not jobs:
            return out
        scored = self.classifier.predict([s for _, s in jobs])
        for (i, sentence), res in zip(jobs, scored, strict=True):
            p = res.probabilities.get(ml[i].event_type, 0.0)
            if i not in out or p > out[i]["score"]:
                out[i] = {"source": ml[i].method, "phrase": sentence[:200], "context": sentence[:300],
                          "score": round(p, 4)}
        return out

    def annotate(self, docs: list[Document]) -> list[Annotation]:
        if not docs:
            return []
        texts = [f"{d.title}. {d.lead}".strip() if d.lead else d.title for d in docs]
        linked = [self.linker.link(d) for d in docs]
        decisions = [self.rules.decide(self.rules.evidence(d)) for d in docs]
        undecided = [i for i, dec in enumerate(decisions) if dec is None]
        cls_texts = [classifier_text(d) for d in docs]
        ml = self._classify(cls_texts, undecided)
        ml_evidence = self._ml_evidence(cls_texts, ml)
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
            macro = macro_evidence(doc, method, event_type)
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
                    event_evidence=(
                        {"source": decisions[i].source, "phrase": decisions[i].phrase,
                         "context": decisions[i].context} if decisions[i] else ml_evidence.get(i, {})),
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
        if entities and (m := ANALYST_ACTION.search(doc.title)):
            entities = [e for e in entities if not any(x.location == "title" and x.start < m.end() for x in e.mentions)]
        if entities and entities[0].relevance >= PRIMARY_MIN_RELEVANCE:
            return entities[0]
        if macro >= MIN_MACRO_EVIDENCE:
            return "MACRO"
        return "NONE"
