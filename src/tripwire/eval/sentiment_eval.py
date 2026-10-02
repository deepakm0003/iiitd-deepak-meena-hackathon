"""Entity-level sentiment evaluation on SEntFiN 1.0 (Sinha et al., 2022; CC BY-NC 4.0, not redistributed).

SEntFiN gives, per headline, the sentiment towards each named entity, and 2,800+ headlines name several
entities, often with conflicting sentiment. That is exactly the claim our sentiment stage makes, so we
compare, on the same FinBERT model:
  - headline:  score the whole headline (what a plain sentiment model does), applied to every entity;
  - clause:    our method, scoring the clause that mentions the entity (nlp/sentiment.py).
FinBERT was trained on Financial PhraseBank, not SEntFiN, so there is no train/test overlap.
"""

import csv
import json
from pathlib import Path

from tripwire.eval.metrics import summary
from tripwire.models import Document
from tripwire.nlp.linking import LinkedEntity, Mention
from tripwire.nlp.sentiment import FinbertSentiment

LABELS = ["negative", "neutral", "positive"]


def load_sentfin(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            decisions = json.loads(row["Decisions"])
            for entity, label in decisions.items():
                if entity in row["Title"] and label in LABELS:
                    rows.append({"title": row["Title"], "entity": entity, "label": label,
                                 "multi": len(decisions) > 1, "conflict": len(set(decisions.values())) > 1})
    return rows


def _entity(name: str, title: str) -> LinkedEntity:
    mention = Mention(surface=name, location="title", start=title.find(name), method="gold", confidence=1.0)
    return LinkedEntity(ticker=name, cik=None, sector="", link_confidence=1.0, relevance=1.0, in_title=True,
                        method="gold", mentions=[mention])


def baseline_predictions(rows: list[dict], model: FinbertSentiment) -> dict[str, list[str]]:
    """Predictions of the two untrained baselines: whole headline, and clause mentioning the entity.

    Both use the BASE FinBERT only (never the fine-tuned entity model), so the comparison stays fixed.
    """
    model = FinbertSentiment({"name": model.name}, entity_model=Path("__no_entity_model__"), clause_split=True)
    titles = sorted({r["title"] for r in rows})
    headline_probs = dict(zip(titles, model.probabilities(titles), strict=True))
    headline_pred = [max(headline_probs[r["title"]], key=headline_probs[r["title"]].get) for r in rows]
    by_title: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_title.setdefault(r["title"], []).append(i)
    clause_pred = [""] * len(rows)
    for title, idx in by_title.items():
        doc = Document(raw_id=0, dedup_key="", source="sentfin", source_type="news", title=title,
                       published_at="2022-01-01T00:00:00Z")
        results = model.for_entities(doc, [_entity(rows[i]["entity"], title) for i in idx])
        for i in idx:
            clause_pred[i] = results[rows[i]["entity"]].label
    return {"headline": headline_pred, "clause": clause_pred}


def evaluate(rows: list[dict], model: FinbertSentiment, limit: int | None = None) -> dict:
    rows = rows[:limit] if limit else rows
    preds = baseline_predictions(rows, model)
    headline_pred, clause_pred = preds["headline"], preds["clause"]

    def subset(mask):
        keep = [i for i, r in enumerate(rows) if mask(r)]
        y = [rows[i]["label"] for i in keep]
        return {"headline": summary(y, [headline_pred[i] for i in keep], LABELS),
                "clause": summary(y, [clause_pred[i] for i in keep], LABELS)}

    return {
        "dataset": "SEntFiN 1.0 (entity-headline pairs)",
        "model": model.name,
        "all": subset(lambda r: True),
        "multi_entity": subset(lambda r: r["multi"]),
        "conflicting_sentiment": subset(lambda r: r["conflict"]),
    }
