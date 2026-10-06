"""Round 4, step 3: fine-tune the whole e5-large encoder (not only a logistic head on frozen embeddings).

Same protocol as scripts/round3_experiment.py, so the numbers are directly comparable:
- the same 5 folds over all human labels (a fold's items are never in its training data);
- training data = recipe v3 weak labels + the human labels of the other folds (repeated 3x, like sample weight 3);
- the whole pipeline is scored (8-K items and rules first, then the model, Earnings guard, verifier, per-class bars).
The frozen-encoder baseline is the `v3+human x3` row of round3_experiment_e5-large-v2_n680.json.
Run on the GPU server: RULES=R4 python scripts/finetune_experiment.py
"""

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("r3", ROOT / "scripts" / "round3_experiment.py")
r3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r3)

MODEL = os.environ.get("FT_MODEL", "intfloat/e5-large-v2")
EPOCHS = int(os.environ.get("FT_EPOCHS", "3"))
LR = float(os.environ.get("FT_LR", "2e-5"))
MAX_LEN = 128
BATCH = 8  # P100 16 GB shared with the live API and NLP daemon
# FT_TRAIN_LAYERS=N trains only the top N encoder layers (and the classifier), for a GPU with less free memory: a full
# fine-tune of e5-large needs ~7.5 GB with AdamW. The round-4 result was a full fine-tune (0 = every layer).
TRAIN_LAYERS = int(os.environ.get("FT_TRAIN_LAYERS", "0"))


def fine_tune_predict(train_texts, train_labels, test_texts, classes, seed=7):
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    torch.manual_seed(seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL, num_labels=len(classes)).to(dev)
    if TRAIN_LAYERS:
        base = model.base_model
        for p in base.embeddings.parameters():
            p.requires_grad = False
        for layer in base.encoder.layer[:-TRAIN_LAYERS]:
            for p in layer.parameters():
                p.requires_grad = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    idx = {c: i for i, c in enumerate(classes)}
    y = torch.tensor([idx[c] for c in train_labels])
    order = list(range(len(train_texts)))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LR, weight_decay=0.01)
    steps = EPOCHS * ((len(order) + BATCH - 1) // BATCH)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)
    # class weights (inverse frequency, capped) so rare classes are not drowned out
    counts = np.bincount(y.numpy(), minlength=len(classes)).astype(float)
    weights = torch.tensor(np.clip(counts.sum() / (len(classes) * np.maximum(counts, 1)), 0.5, 5.0),
                           dtype=torch.float, device=dev)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    rng = np.random.default_rng(seed)
    model.train()
    for _ in range(EPOCHS):
        rng.shuffle(order)
        for start in range(0, len(order), BATCH):
            b = order[start:start + BATCH]
            enc = tok(["query: " + train_texts[i] for i in b], truncation=True, max_length=MAX_LEN, padding=True,
                      return_tensors="pt").to(dev)
            with torch.autocast(device_type=dev, enabled=dev == "cuda"):
                loss = loss_fn(model(**enc).logits, y[b].to(dev))
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
    model.eval()
    probs = []
    loader = DataLoader(list(range(len(test_texts))), batch_size=64)
    with torch.no_grad():
        for b in loader:
            enc = tok(["query: " + test_texts[i] for i in b.tolist()], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors="pt").to(dev)
            probs.extend(torch.softmax(model(**enc).logits.float(), dim=-1).cpu().numpy().tolist())
    del model
    torch.cuda.empty_cache()
    return [dict(zip(classes, p, strict=True)) for p in probs]


def main() -> int:
    from tripwire import gold
    from tripwire.config import load_yaml
    from tripwire.factory import build_http, build_store
    from tripwire.nlp import training_data as td
    from tripwire.nlp.classifier import ClassResult, EventClassifier, _result
    from tripwire.nlp.engine import _guard_earnings, _select, classifier_text
    from tripwire.nlp.filing_lead import with_filing_leads
    from tripwire.settings import get_settings

    settings = get_settings()
    store, http = build_store(settings), build_http(settings)
    labels = {}
    for name in r3.LABEL_FILES:
        for row in gold.read_jsonl(r3.GOLD / name):
            labels[row["key"]] = {**row, "set": name.split("_")[0]}
    docs = with_filing_leads(store, store.iter_documents())
    by_key = {d.dedup_key: d for d in docs}
    items = [v for k, v in labels.items() if k in by_key]
    y = [it["event_type"] for it in items]
    texts = [classifier_text(by_key[it["key"]]) for it in items]
    folds = [r3.fold_of(it["key"]) for it in items]
    has_text = [i for i, t in enumerate(texts) if t]
    print(f"{len(items)} items; model {MODEL}; epochs {EPOCHS}; lr {LR}", flush=True)

    rule_name = os.environ.get("RULES", "R4")
    rules = r3.rules_variant(load_yaml("event_rules.yaml"), load_yaml("taxonomy.yaml"), r3.RULE_VARIANTS[rule_name])
    decisions = [rules.decide(rules.evidence(by_key[it["key"]])) for it in items]
    clf = EventClassifier()
    zs = dict(zip(has_text, clf.predict_zero_shot([texts[i] for i in has_text]), strict=True))

    exclude = set()
    for name in r3.CANDIDATE_FILES:
        exclude |= {c["key"] for c in gold.read_jsonl(r3.GOLD / name)}
    rule_ex, other_ex = td.in_domain_examples(store, docs, exclude)
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    edgar = td.edgar_examples(store, utc("2023-01-01"), utc("2024-12-31"))
    data = td.recipe_v3(edgar, td.download_twitter_topic(http, "train"), rule_ex, other_ex)
    classes = sorted({e.label for e in data} | set(y))

    probs = {}
    for f in range(r3.FOLDS):
        train = [i for i in has_text if folds[i] != f]
        test = [i for i in has_text if folds[i] == f]
        tr_texts = [e.text for e in data] + [texts[i] for i in train for _ in range(3)]
        tr_labels = [e.label for e in data] + [y[i] for i in train for _ in range(3)]
        for i, p in zip(test, fine_tune_predict(tr_texts, tr_labels, [texts[i] for i in test], classes), strict=True):
            probs[i] = p
        print(f"fold {f} done", flush=True)

    cfg = load_yaml("models.yaml")["event_classifier"]
    policy = {"min_confidence": cfg["min_confidence"], "verify_classes": set(cfg["verify"]["classes"]),
              "verifier_min_p": cfg["verify"]["min_p"],
              "verifier_min_p_by_class": cfg["verify"].get("min_p_by_class", {})}
    class_min = {"Product Launch": 0.5, "Merger/Acquisition": 0.5}
    pred = []
    for i, dec in enumerate(decisions):
        if dec is not None:
            pred.append(dec.event_type)
            continue
        if i not in probs:
            pred.append("Other")
            continue
        r = _guard_earnings(_result(probs[i], "head"), texts[i])
        if r.confidence < class_min.get(r.event_type, 0.0):
            r = ClassResult("Other", r.probabilities, r.confidence, "head:abstain")
        pred.append(_select(r, zs.get(i), policy).event_type)
    out = {"run_at": datetime.now(UTC).isoformat(), "model": MODEL, "epochs": EPOCHS, "lr": LR, "rules": rule_name,
           "train_layers": TRAIN_LAYERS or "all",
           "policy": "P2 PL/MA>=0.5", "n_items": len(items), "all": r3.scores(pred, y)}
    for s in sorted({it["set"] for it in items}):
        idx = [i for i, it in enumerate(items) if it["set"] == s]
        out[s] = r3.scores([pred[i] for i in idx], [y[i] for i in idx])
    print(json.dumps({k: out[k] for k in ("model", "rules")}), "acc", out["all"]["accuracy"], "mF1",
          out["all"]["macro_f1"], flush=True)
    path = ROOT / "docs" / "results" / f"finetune_experiment_{MODEL.split('/')[-1]}_{rule_name}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
