"""ML event classification (layer 3 of the hybrid): SetFit, with a zero-shot NLI fallback.

Layer 1 (8-K items) and layer 2 (high-precision rules) decide first, in nlp/events.py. This layer handles
everything they leave undecided. SetFit (few-shot fine-tuning of a sentence-transformer + logistic head)
is trained on weak labels; zero-shot (DeBERTa-v3 NLI) covers classes with little training data and serves
as a comparison baseline. Class probabilities are temperature-calibrated on the validation split (Part 3).
"""

from dataclasses import dataclass
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.settings import ROOT

# Natural-language descriptions used as zero-shot hypotheses ("This financial news item is about {}.").
DESCRIPTIONS = {
    "Credit Event": "a credit event such as a bankruptcy, a default, a credit rating downgrade or a liquidity crisis",
    "Geopolitical": "geopolitics such as war, sanctions, tariffs or trade disputes between countries",
    "Macroeconomic": "the economy, inflation, interest rates, central banks or financial markets overall",
    "Merger/Acquisition": "a merger, an acquisition, a takeover or a divestiture",
    "Regulatory/Legal": "a lawsuit, a fine, a regulatory investigation or a government approval decision",
    "Cyber/Operational": "a cyberattack, a data breach, an outage, a product recall or a strike",
    "Natural Disaster/Supply Chain": "a natural disaster, a pandemic or a supply chain disruption",
    "Earnings": "company earnings, quarterly financial results or guidance",
    "Management Change": "a change of chief executive, management or board members",
    "Product Launch": "the launch of a new product or service",
    "Other": "general business news, stock market commentary or dividends",
}


@dataclass
class ClassResult:
    event_type: str
    probabilities: dict[str, float]
    confidence: float
    method: str  # setfit | zero_shot


class EventClassifier:
    """SetFit if a trained model exists, otherwise zero-shot. Both return calibrated-ready probabilities."""

    def __init__(self, cfg: dict | None = None, temperature: float = 1.0) -> None:
        models = cfg or load_yaml("models.yaml")
        self.classes = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]
        self.setfit_path = ROOT / models["event_classifier"]["path"]
        self.zero_shot_cfg = models["zero_shot"]
        self.temperature = temperature
        self._setfit = None
        self._zero_shot = None
        self._head = None
        self._head_embedder = None

    @property
    def has_setfit(self) -> bool:
        return (self.setfit_path / "model_head.pkl").exists()

    @property
    def has_head(self) -> bool:
        return HEAD_PATH.exists()

    @property
    def method(self) -> str:
        """Which variant predict() uses: the trained variant shipped for this install, else zero-shot."""
        preferred = _shipped_variant()
        if preferred == "setfit" and self.has_setfit:
            return "setfit"
        if self.has_head:
            return "head"
        return "setfit" if self.has_setfit else "zero_shot"

    def predict(self, texts: list[str]) -> list[ClassResult]:
        if not texts:
            return []
        method = self.method
        if method == "setfit":
            return self._predict_setfit(texts)
        if method == "head":
            return self._predict_head(texts)
        return self.predict_zero_shot(texts)

    def _predict_head(self, texts: list[str]) -> list[ClassResult]:
        import pickle

        if self._head is None:
            from tripwire.nlp.embeddings import Embedder

            with open(HEAD_PATH, "rb") as fh:
                self._head = pickle.load(fh)
            self._head_embedder = Embedder({"name": self._head["base_model"]})
        vectors = self._head_embedder.encode(texts)
        probs = self._head["classifier"].predict_proba(vectors)
        labels = list(self._head["labels"])
        return [_result(self._calibrate(dict(zip(labels, row.tolist(), strict=True))), "head") for row in probs]

    def _calibrate(self, probabilities: dict[str, float]) -> dict[str, float]:
        if self.temperature == 1.0:
            return probabilities
        import math

        scaled = {k: math.exp(math.log(max(v, 1e-9)) / self.temperature) for k, v in probabilities.items()}
        total = sum(scaled.values())
        return {k: v / total for k, v in scaled.items()}

    def _predict_setfit(self, texts: list[str]) -> list[ClassResult]:
        import numpy as np

        if self._setfit is None:
            from setfit import SetFitModel

            from tripwire.nlp.device import device

            self._setfit = SetFitModel.from_pretrained(str(self.setfit_path), device=device())
        probs = np.asarray(self._setfit.predict_proba(texts))
        labels = list(self._setfit.labels or self.classes)
        if self.temperature != 1.0:  # temperature scaling on log-probabilities
            logits = np.log(np.clip(probs, 1e-9, 1)) / self.temperature
            probs = np.exp(logits - logits.max(axis=1, keepdims=True))
            probs /= probs.sum(axis=1, keepdims=True)
        return [_result(dict(zip(labels, row.tolist(), strict=True)), "setfit") for row in probs]

    def predict_zero_shot(self, texts: list[str]) -> list[ClassResult]:
        if self._zero_shot is None:
            from transformers import pipeline

            from tripwire.nlp.device import device

            self._zero_shot = pipeline("zero-shot-classification", model=self.zero_shot_cfg["name"],
                                       device=0 if device() == "cuda" else -1)
        hypotheses = [DESCRIPTIONS[c] for c in self.classes]
        back = dict(zip(hypotheses, self.classes, strict=True))
        outputs = self._zero_shot(texts, candidate_labels=hypotheses, multi_label=False,
                                  hypothesis_template=self.zero_shot_cfg["hypothesis_template"])
        outputs = [outputs] if isinstance(outputs, dict) else outputs
        return [
            _result({back[label]: score for label, score in zip(o["labels"], o["scores"], strict=True)}, "zero_shot")
            for o in outputs
        ]


def _result(probabilities: dict[str, float], method: str) -> ClassResult:
    best = max(probabilities, key=probabilities.get)
    return ClassResult(best, {k: round(v, 4) for k, v in probabilities.items()}, round(probabilities[best], 4), method)


HEAD_PATH = ROOT / "models" / "event_head.pkl"
REPORT_PATH = ROOT / "docs" / "results" / "event_classifier_training.json"


def _shipped_variant() -> str | None:
    if REPORT_PATH.exists():
        import json

        return json.loads(REPORT_PATH.read_text(encoding="utf-8")).get("shipped_for_lite_mode")
    return None


def setfit_path() -> Path:
    return ROOT / load_yaml("models.yaml")["event_classifier"]["path"]
