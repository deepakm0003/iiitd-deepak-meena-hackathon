"""Entity-level financial sentiment, plus the evidence sentences behind each score.

Two models:
  - entity model (preferred, when trained): FinBERT fine-tuned on (sentence, entity) pairs from SEntFiN.
    Measured on SEntFiN's held-out test split: macro-F1 0.888 vs 0.662 for plain FinBERT, and 0.867 vs 0.437
    on headlines where different companies get opposite sentiment (docs/results/sentiment_finetune.json).
  - base model: ProsusAI/finbert on the text alone. Used for macro items (no entity) and as the fallback.

Score = P(positive) - P(negative) in [-1, 1], averaged over the sentences that mention the entity, with the
headline weighted double. Clause splitting ("X beats while Y misses") was tried as a cheaper alternative to
the pair model and measured no gain (0.651 vs 0.662), so it is off by default and kept only to reproduce
that comparison.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.models import Document
from tripwire.nlp.linking import LinkedEntity
from tripwire.nlp.text import split_sentences
from tripwire.settings import ROOT

CLAUSE_SPLIT = re.compile(r";|,?\s+\b(?:while|whereas|but|although|though|as opposed to|unlike|even as)\b\s+", re.I)
TITLE_WEIGHT = 2.0
ENTITY_MODEL_DIR = ROOT / "models" / "sentiment_entity"


@dataclass
class SentimentResult:
    score: float                      # P(pos) - P(neg), weighted mean
    label: str                        # positive | negative | neutral (argmax of mean probabilities)
    probabilities: dict[str, float]
    evidence: list[dict] = field(default_factory=list)  # [{"text", "score", "location"}]
    method: str = "sentence"          # entity_pair | sentence | clause | document


class _Classifier:
    """A sequence classifier that scores single texts or (text, entity) pairs in batches."""

    def __init__(self, name: str, max_length: int, batch_size: int, device: str | None) -> None:
        self.name, self.max_length, self.batch_size = name, max_length, batch_size
        self._device = device
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        from tripwire.nlp.device import device

        self._device = self._device or device()
        self._tokenizer = AutoTokenizer.from_pretrained(self.name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.name).to(self._device).eval()
        self._labels = [self._model.config.id2label[i].lower() for i in range(self._model.config.num_labels)]

    def probabilities(self, texts: list[str], pairs: list[str] | None = None) -> list[dict[str, float]]:
        import torch

        if not texts:
            return []
        self._load()
        out: list[dict[str, float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            second = pairs[start : start + self.batch_size] if pairs is not None else None
            encoded = self._tokenizer(batch, second, padding=True, truncation=True, max_length=self.max_length,
                                      return_tensors="pt").to(self._device)
            with torch.no_grad():
                probs = torch.softmax(self._model(**encoded).logits, dim=-1).cpu().tolist()
            out.extend({label: p for label, p in zip(self._labels, row, strict=True)} for row in probs)
        return out


class FinbertSentiment:
    def __init__(self, cfg: dict | None = None, device: str | None = None, entity_model: Path | None = None,
                 clause_split: bool = False) -> None:
        cfg = cfg or load_yaml("models.yaml")["sentiment"]
        self.name = cfg["name"]
        max_length, batch = int(cfg.get("max_length", 128)), int(cfg.get("batch_size", 32))
        self._base = _Classifier(self.name, max_length, batch, device)
        path = entity_model if entity_model is not None else ENTITY_MODEL_DIR
        has_entity_model = (Path(path) / "config.json").exists()
        self._entity = _Classifier(str(path), max_length, batch, device) if has_entity_model else None
        self.clause_split = clause_split

    @property
    def entity_model(self) -> str | None:
        return self._entity.name if self._entity else None

    def probabilities(self, texts: list[str]) -> list[dict[str, float]]:
        """Base FinBERT probabilities for whole texts."""
        return self._base.probabilities(texts)

    def pair_probabilities(self, texts: list[str], entities: list[str]) -> list[dict[str, float]]:
        """Entity-model probabilities for (text, entity) pairs."""
        return self._entity.probabilities(texts, entities)

    # ------------------------------------------------------------------------------------------------
    def for_entity(self, doc: Document, entity: LinkedEntity | None) -> SentimentResult:
        key = entity.ticker if entity else "MACRO"
        return self.for_entities(doc, [entity] if entity else [])[key]

    def for_entities(self, doc: Document, entities: list[LinkedEntity]) -> dict[str, SentimentResult]:
        """Score each entity, plus a document-level 'MACRO' score, with batched forward passes."""
        results: dict[str, SentimentResult] = {}
        macro_units = self._units(doc, None)
        plans = {e.ticker: (e, self._units(doc, e)) for e in entities}
        if self._entity and plans:
            texts, names, owners = [], [], []
            for ticker, (entity, units) in plans.items():
                name = _entity_name(entity)
                for unit in units:
                    texts.append(unit[0])
                    names.append(name)
                    owners.append(ticker)
            probs = iter(self.pair_probabilities(texts, names))
            for ticker, (_, units) in plans.items():
                results[ticker] = _aggregate(units, [next(probs) for _ in units], "entity_pair")
            base_units = macro_units
        else:
            base_units = [u for _, units in plans.values() for u in units] + macro_units
        base_probs = iter(self.probabilities([u[0] for u in base_units]))
        if not self._entity:
            for ticker, (_, units) in plans.items():
                results[ticker] = _aggregate(units, [next(base_probs) for _ in units], units[0][2])
        results["MACRO"] = _aggregate(macro_units, [next(base_probs) for _ in macro_units], "document")
        return results

    def _units(self, doc: Document, entity: LinkedEntity | None) -> list[tuple[str, str, str, float]]:
        """(text, location, method, weight) units to score for this entity."""
        pieces = [("title", doc.title)] + [("lead", s) for s in split_sentences(doc.lead)]
        weight = lambda loc: TITLE_WEIGHT if loc == "title" else 1.0  # noqa: E731
        if entity is None:
            return [(text, loc, "document", weight(loc)) for loc, text in pieces]
        surfaces = {m.surface for m in entity.mentions if m.location != "hint"}
        units: list[tuple[str, str, str, float]] = []
        for location, sentence in pieces:
            if not any(s in sentence for s in surfaces):
                continue
            if self.clause_split:
                clauses = [c for c in CLAUSE_SPLIT.split(sentence) if c and c.strip()]
                mine = [c for c in clauses if any(s in c for s in surfaces)]
                if len(clauses) > 1 and mine and len(mine) < len(clauses):
                    units += [(c.strip(), location, "clause", weight(location)) for c in mine]
                    continue
            units.append((sentence, location, "sentence", weight(location)))
        if not units:  # linked only through a hint: fall back to the headline, flagged as document-level
            units.append((doc.title, "title", "document", TITLE_WEIGHT))
        return units


def _entity_name(entity: LinkedEntity) -> str:
    """The surface form the text actually uses for the entity (what the pair model was trained on)."""
    textual = [m.surface for m in entity.mentions if m.location != "hint" and not m.surface.startswith("$")]
    return max(textual, key=len) if textual else entity.ticker


def _aggregate(units, probs, method: str) -> SentimentResult:
    total = sum(u[3] for u in units) or 1.0
    labels = probs[0].keys() if probs else ("positive", "negative", "neutral")
    mean = {lab: sum(p[lab] * u[3] for p, u in zip(probs, units, strict=True)) / total for lab in labels}
    score = mean.get("positive", 0.0) - mean.get("negative", 0.0)
    evidence = sorted(
        ({"text": u[0], "score": round(p.get("positive", 0) - p.get("negative", 0), 3), "location": u[1]}
         for u, p in zip(units, probs, strict=True)),
        key=lambda e: -abs(e["score"]),
    )[:3]
    return SentimentResult(
        score=round(score, 4),
        label=max(mean, key=mean.get),
        probabilities={k: round(v, 4) for k, v in mean.items()},
        evidence=evidence,
        method=method,
    )
