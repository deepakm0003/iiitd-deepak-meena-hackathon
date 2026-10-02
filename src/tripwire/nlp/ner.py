"""Zero-shot financial NER with GLiNER (urchade/gliner_multi-v2.1, Apache 2.0).

GLiNER finds spans for arbitrary entity types given as text labels, without task-specific training. We use it
for what dictionary linking cannot do: counterparties and companies outside the universe, regulators, rating
agencies, countries, and money amounts. Its spans enrich the event frame (target, places, amounts); linking
to tickers stays with the dictionary linker, which has confidence and NIL.
"""

from dataclasses import dataclass

from tripwire.config import load_yaml


@dataclass(frozen=True)
class Span:
    text: str
    label: str
    score: float
    start: int
    end: int


class GlinerNer:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or load_yaml("models.yaml")["ner"]
        self.name = cfg["name"]
        self.labels = list(cfg["labels"])
        self.threshold = float(cfg.get("threshold", 0.5))
        self._model = None

    def _load(self):
        if self._model is None:
            from gliner import GLiNER

            from tripwire.nlp.device import device

            self._model = GLiNER.from_pretrained(self.name).to(device())
        return self._model

    def extract(self, texts: list[str]) -> list[list[Span]]:
        model = self._load()
        # from_pretrained returns a concrete GLiNER subclass; batch_predict_entities is the stable batch API.
        predict = getattr(model, "batch_predict_entities", None) or model.inference
        batches = predict(texts, self.labels, threshold=self.threshold)
        return [
            [Span(e["text"], e["label"], round(float(e["score"]), 3), e["start"], e["end"]) for e in entities]
            for entities in batches
        ]


def enrich_frame(frame: dict, spans: list[Span]) -> dict:
    """Fill empty frame slots from NER spans; never overwrite rule-based slots (they are more precise)."""
    out = dict(frame)
    orgs = [s.text for s in spans if s.label in {"company", "bank"}]
    if not out.get("target") and len(orgs) > 1:
        out["target"] = orgs[1]  # the first organisation is usually the actor
    # GLiNER's span boundaries are good but its type labels are noisy (it called the FTC a rating agency and
    # "yields" a money amount), so slots only accept confident spans of plausible shape.
    regulators = [s.text for s in spans
                  if s.label in {"regulator", "government agency", "credit rating agency"} and s.score >= 0.6]
    if regulators:
        out["authorities"] = list(dict.fromkeys(regulators))[:3]
    places = [s.text for s in spans if s.label == "country" and s.score >= 0.6]
    out["places"] = list(dict.fromkeys([*out.get("places", []), *places]))[:5]
    amounts = [s.text for s in spans if s.label == "money amount" and any(ch.isdigit() for ch in s.text)]
    out["amounts"] = list(dict.fromkeys([*out.get("amounts", []), *amounts]))[:5]
    out["ner_spans"] = [{"text": s.text, "label": s.label, "score": s.score} for s in spans][:15]
    return out
