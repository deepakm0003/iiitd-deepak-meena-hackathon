"""Fine-tune FinBERT for ENTITY-LEVEL sentiment: input = (headline, entity) as a sentence pair.

Why: on SEntFiN, scoring the whole headline (plain FinBERT) or the clause that mentions the entity both fail
on multi-entity headlines with conflicting sentiment (measured: macro-F1 about 0.47). A pair model learns
which entity the sentiment is about.

Data: SEntFiN 1.0 (CC BY-NC 4.0, used for non-commercial research only). Split by headline hash
(80/10/10) so the same headline never sits in two splits. Baselines are re-scored on the same test split.
"""

import hashlib
import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path

from tripwire.eval.metrics import summary
from tripwire.eval.sentiment_eval import LABELS

log = logging.getLogger(__name__)


def split_of(title: str) -> str:
    bucket = int(hashlib.sha256(title.encode("utf-8")).hexdigest(), 16) % 10
    return "test" if bucket == 9 else "valid" if bucket == 8 else "train"


def predict_pairs(model, tokenizer, pairs: list[tuple[str, str]], device: str, batch_size: int = 64) -> list[str]:
    import torch

    labels = [model.config.id2label[i].lower() for i in range(model.config.num_labels)]
    out = []
    model.eval()
    for start in range(0, len(pairs), batch_size):
        batch = pairs[start : start + batch_size]
        enc = tokenizer([p[0] for p in batch], [p[1] for p in batch], padding=True, truncation=True,
                        max_length=96, return_tensors="pt").to(device)
        with torch.no_grad():
            out += [labels[i] for i in model(**enc).logits.argmax(-1).cpu().tolist()]
    return out


def train(rows: list[dict], base: str, out_dir: Path, report_path: Path, epochs: int = 3, lr: float = 2e-5,
          batch_size: int = 32, seed: int = 13, baseline: dict | None = None) -> dict:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from tripwire.nlp.device import device

    random.seed(seed)
    torch.manual_seed(seed)
    dev = device()
    splits = {name: [r for r in rows if split_of(r["title"]) == name] for name in ("train", "valid", "test")}
    tokenizer = AutoTokenizer.from_pretrained(base)
    model = AutoModelForSequenceClassification.from_pretrained(base).to(dev)
    label_id = {model.config.id2label[i].lower(): i for i in range(model.config.num_labels)}

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    train_rows = list(splits["train"])
    steps = epochs * ((len(train_rows) + batch_size - 1) // batch_size)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda s: max(0.0, 1 - s / max(1, steps)))
    best_f1, history = -1.0, []
    for epoch in range(epochs):
        model.train()
        random.shuffle(train_rows)
        for start in range(0, len(train_rows), batch_size):
            batch = train_rows[start : start + batch_size]
            enc = tokenizer([r["title"] for r in batch], [r["entity"] for r in batch], padding=True,
                            truncation=True, max_length=96, return_tensors="pt").to(dev)
            target = torch.tensor([label_id[r["label"]] for r in batch], device=dev)
            loss = torch.nn.functional.cross_entropy(model(**enc).logits, target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
        valid_pred = predict_pairs(model, tokenizer, [(r["title"], r["entity"]) for r in splits["valid"]], dev)
        valid = summary([r["label"] for r in splits["valid"]], valid_pred, LABELS)
        history.append({"epoch": epoch + 1, "valid_macro_f1": valid["macro_f1"]})
        log.info("epoch %d: valid macro-F1 %.3f", epoch + 1, valid["macro_f1"])
        if valid["macro_f1"] > best_f1:  # keep the best epoch on VALIDATION (test is untouched until the end)
            best_f1 = valid["macro_f1"]
            model.save_pretrained(str(out_dir))
            tokenizer.save_pretrained(str(out_dir))

    best = AutoModelForSequenceClassification.from_pretrained(str(out_dir)).to(dev)
    test = splits["test"]
    y = [r["label"] for r in test]
    pair_pred = predict_pairs(best, tokenizer, [(r["title"], r["entity"]) for r in test], dev)
    report = {
        "trained_at": datetime.now(UTC).isoformat(),
        "base_model": base,
        "data": "SEntFiN 1.0, split by headline hash 80/10/10",
        "sizes": {k: len(v) for k, v in splits.items()},
        "history": history,
        "test": {"pair_finetuned": summary(y, pair_pred, LABELS)},
    }
    conflict = [i for i, r in enumerate(test) if r["conflict"]]
    report["test_conflicting"] = {
        "pair_finetuned": summary([y[i] for i in conflict], [pair_pred[i] for i in conflict], LABELS)
    }
    if baseline:
        for name, preds in baseline.items():
            report["test"][name] = summary(y, preds, LABELS)
            report["test_conflicting"][name] = summary([y[i] for i in conflict], [preds[i] for i in conflict], LABELS)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
