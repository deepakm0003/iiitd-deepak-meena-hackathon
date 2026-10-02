"""Train and compare event classifiers on weak labels (run on the GPU server; outputs are small files).

Two variants are trained on the same balanced data and compared on the validation split:
  - 'head':   frozen MiniLM embeddings + logistic regression. Tiny artefact (a few KB, committed to the repo),
              so the README Quickstart needs no extra download.
  - 'setfit': SetFit contrastive fine-tuning of MiniLM + logistic head. Usually more accurate, ~90 MB.
The variant shipped for lite mode is whichever wins on validation, unless the gap is small, in which case
the tiny one is preferred (efficiency over a marginal gain; both numbers are reported).
"""

import json
import logging
import pickle
from datetime import UTC, datetime
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.nlp.classifier import HEAD_PATH
from tripwire.nlp.training_data import Example, describe

log = logging.getLogger(__name__)


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> float:
    from sklearn.metrics import f1_score

    return float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))


def train_head(train: list[Example], embed) -> object:
    from sklearn.linear_model import LogisticRegression

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=2.0)
    clf.fit(embed([e.text for e in train]), [e.label for e in train])
    return clf


def train_setfit(train: list[Example], base: str, out_dir: Path, epochs: int = 1, iterations: int = 20):
    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments

    labels = sorted({e.label for e in train})
    model = SetFitModel.from_pretrained(base, labels=labels)
    args = TrainingArguments(batch_size=32, num_epochs=epochs, num_iterations=iterations, seed=13)
    trainer = Trainer(model=model, args=args,
                      train_dataset=Dataset.from_dict({"text": [e.text for e in train],
                                                       "label": [e.label for e in train]}))
    trainer.train()
    model.save_pretrained(str(out_dir))
    return model


def run(train: list[Example], valid: list[Example], out_dir: Path, report_path: Path) -> dict:
    from sentence_transformers import SentenceTransformer

    from tripwire.nlp.device import device

    cfg = load_yaml("models.yaml")["event_classifier"]
    labels = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]
    body = SentenceTransformer(cfg["base"], device=device())

    def embed(texts):
        return body.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)

    head = train_head(train, embed)
    head_pred = list(head.predict(embed([e.text for e in valid])))
    labels = [c for c in labels if c in {e.label for e in valid}]  # macro-F1 over classes present in valid
    report = {
        "trained_at": datetime.now(UTC).isoformat(),
        "base_model": cfg["base"],
        "train": describe(train),
        "valid": describe(valid),
        "head": {"macro_f1_valid": macro_f1([e.label for e in valid], head_pred, labels)},
    }
    HEAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HEAD_PATH, "wb") as fh:
        pickle.dump({"classifier": head, "base_model": cfg["base"], "labels": list(head.classes_)}, fh)
    log.info("head macro-F1 (valid) = %.3f", report["head"]["macro_f1_valid"])

    model = train_setfit(train, cfg["base"], out_dir)
    setfit_pred = list(model.predict([e.text for e in valid]))
    report["setfit"] = {"macro_f1_valid": macro_f1([e.label for e in valid], setfit_pred, labels)}
    log.info("setfit macro-F1 (valid) = %.3f", report["setfit"]["macro_f1_valid"])
    gap = report["setfit"]["macro_f1_valid"] - report["head"]["macro_f1_valid"]
    report["shipped_for_lite_mode"] = "setfit" if gap > 0.03 else "head"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
