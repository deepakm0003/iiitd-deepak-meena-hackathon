"""Round 3 experiment: fixes for the errors found on the fresh test set, judged by 5-fold cross-validation over
all 478 human labels (the 296 earlier gold items plus the 182 fresh-test items, which are spent and are now
development data). Nothing here is a final result: the winner is validated on a NEW fresh test set.

Compared, as full pipelines (8-K items and rules first, then head, Earnings guard, selection with the verifier):
- rule variants: `disaster` excluding legal stories, `macro_data` on the headline only;
- heads: the shipped head, recipe v3 refit (no human labels), and v3 + the human labels of the training folds
  (sample weight 1 or 3); a fold's own items are never in its training data;
- selection policies: Product Launch added to the verified classes, and/or a higher head bar (0.5) for
  Product Launch and Merger/Acquisition.
Run on the GPU server: python scripts/round3_experiment.py
"""

import copy
import hashlib
import itertools
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from tripwire import gold
from tripwire.config import load_yaml
from tripwire.eval.gold_eval import wilson
from tripwire.factory import build_http, build_store
from tripwire.nlp import training_data as td
from tripwire.nlp.classifier import ClassResult, EventClassifier, _result
from tripwire.nlp.device import device
from tripwire.nlp.engine import _guard_earnings, _select, classifier_text
from tripwire.nlp.events import EventRules
from tripwire.nlp.filing_lead import with_filing_leads
from tripwire.scoring.signals import alert_tier
from tripwire.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
LABEL_FILES = ("human_check.jsonl", "fresh_labels.jsonl")
CANDIDATE_FILES = ("candidates.jsonl", "fresh_candidates.jsonl")
ENCODER = os.environ.get("ENCODER", "BAAI/bge-base-en-v1.5")  # e.g. ENCODER=BAAI/bge-large-en-v1.5
FOLDS = 5
LEGAL = (r"\b(supreme court|court|lawsuits?|sues|sued|suing|litigation|trial|verdict|judge|ruling|plaintiffs?|"
         r"class action|case)\b")
RULE_VARIANTS = {
    "R0": {},
    "R1": {"disaster": {"exclude": LEGAL}},
    "R2": {"macro_data": {"scope": "title"}},
    "R3": {"disaster": {"exclude": LEGAL}, "macro_data": {"scope": "title"}},
}
WATCH = ("Product Launch", "Merger/Acquisition", "Credit Event", "Macroeconomic", "Other")


def fold_of(key: str) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % FOLDS


def rules_variant(base: dict, taxonomy: dict, changes: dict) -> EventRules:
    cfg = copy.deepcopy(base)
    for rule in cfg["rules"]:
        rule.update(changes.get(rule["id"], {}))
    return EventRules(cfg, taxonomy)


def scores(pred: list[str], gold_y: list[str]) -> dict:
    from sklearn.metrics import f1_score

    present = sorted(set(gold_y))
    pairs = list(zip(pred, gold_y, strict=True))
    assigned = [(p, t) for p, t in pairs if p != "Other"]
    out = {"n": len(pairs), "accuracy": round(sum(p == t for p, t in pairs) / len(pairs), 4),
           "macro_f1": round(float(f1_score(gold_y, pred, labels=present, average="macro", zero_division=0)), 4),
           "alert_precision": round(sum(p == t for p, t in assigned) / max(1, len(assigned)), 4),
           "alerts": len(assigned)}
    for c in WATCH:
        tp = sum(p == c and t == c for p, t in pairs)
        out[c] = {"pred": sum(p == c for p, _ in pairs), "true": sum(t == c for _, t in pairs), "tp": tp}
    return out


def main() -> int:
    settings = get_settings()
    store, http = build_store(settings), build_http(settings)
    labels: dict[str, dict] = {}
    for name in LABEL_FILES:
        for row in gold.read_jsonl(GOLD / name):
            labels[row["key"]] = {**row, "set": name.split("_")[0]}
    docs = with_filing_leads(store, store.iter_documents())
    by_key = {d.dedup_key: d for d in docs}
    items = [v for k, v in labels.items() if k in by_key]
    y = [it["event_type"] for it in items]
    texts = [classifier_text(by_key[it["key"]]) for it in items]
    folds = [fold_of(it["key"]) for it in items]
    print(f"{len(items)} human-labelled items; folds {np.bincount(folds).tolist()}", flush=True)

    # ---- rule decisions per variant, and per-rule precision on all items
    base_cfg, taxonomy = load_yaml("event_rules.yaml"), load_yaml("taxonomy.yaml")
    confirmed = set(base_cfg["confirmed_sources"])
    decisions = {}
    rule_report = {}
    for name, changes in RULE_VARIANTS.items():
        rules = rules_variant(base_cfg, taxonomy, changes)
        decisions[name] = [rules.decide(rules.evidence(by_key[it["key"]])) for it in items]
        per = defaultdict(list)
        for dec, t in zip(decisions[name], y, strict=True):
            if dec is not None and dec.event_type != "Other":
                src = dec.source if dec.source.startswith("rule") else dec.source.split(":")[0]
                per[src].append(dec.event_type == t)
        rule_report[name] = {s: f"{sum(v)}/{len(v)}" for s, v in sorted(per.items())}
    print("per-rule precision:", json.dumps(rule_report, indent=1), flush=True)

    # ---- model inputs: zero-shot verifier and the shipped head, for every item with text
    clf = EventClassifier()
    has_text = [i for i, t in enumerate(texts) if t]
    zs = dict(zip(has_text, clf.predict_zero_shot([texts[i] for i in has_text]), strict=True))
    heads = {"shipped": dict(zip(has_text, [r.probabilities for r in clf._predict_head([texts[i] for i in has_text])],
                                 strict=True))}

    # ---- recipe v3 training data, excluding every labelled candidate and near-duplicates
    exclude = set()
    for name in CANDIDATE_FILES:
        exclude |= {c["key"] for c in gold.read_jsonl(GOLD / name)}
    rule_ex, other_ex = td.in_domain_examples(store, docs, exclude)
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    edgar = td.edgar_examples(store, utc("2023-01-01"), utc("2024-12-31"))
    data = td.recipe_v3(edgar, td.download_twitter_topic(http, "train"), rule_ex, other_ex)
    print("v3 training set:", td.describe(data), flush=True)

    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression

    enc = SentenceTransformer(ENCODER, device=device())
    embed = lambda t: enc.encode(t, batch_size=64, normalize_embeddings=True, show_progress_bar=False)  # noqa: E731
    x_train, y_train = embed([e.text for e in data]), [e.label for e in data]
    x_items = embed([t or " " for t in texts])

    def fit(extra: list[int], weight: float):
        x = np.vstack([x_train, x_items[extra]]) if extra else x_train
        yy = y_train + [y[i] for i in extra]
        sw = np.array([1.0] * len(y_train) + [weight] * len(extra))
        return LogisticRegression(max_iter=3000, class_weight="balanced", C=2.0).fit(x, yy, sample_weight=sw)

    v3 = fit([], 1.0)
    heads["v3"] = {i: dict(zip(v3.classes_, row.tolist(), strict=True))
                   for i, row in zip(has_text, v3.predict_proba(x_items[has_text]), strict=True)}
    for weight in (1.0, 3.0):
        probs = {}
        for f in range(FOLDS):
            train = [i for i in has_text if folds[i] != f]
            test = [i for i in has_text if folds[i] == f]
            m = fit(train, weight)
            for i, row in zip(test, m.predict_proba(x_items[test]), strict=True):
                probs[i] = dict(zip(m.classes_, row.tolist(), strict=True))
        heads[f"v3+human x{weight:g}"] = probs
        print("fitted", f"v3+human x{weight:g}", flush=True)

    # ---- selection policies
    cfg = load_yaml("models.yaml")["event_classifier"]
    base_policy = {"min_confidence": cfg["min_confidence"], "verify_classes": set(cfg["verify"]["classes"]),
                   "verifier_min_p": cfg["verify"]["min_p"],
                   "verifier_min_p_by_class": cfg["verify"].get("min_p_by_class", {})}
    policies = {
        "P0": (base_policy, {}),
        "P1 verify PL": ({**base_policy, "verify_classes": base_policy["verify_classes"] | {"Product Launch"}}, {}),
        "P2 PL/MA>=0.5": (base_policy, {"Product Launch": 0.5, "Merger/Acquisition": 0.5}),
        "P3 P1+P2": ({**base_policy, "verify_classes": base_policy["verify_classes"] | {"Product Launch"}},
                     {"Product Launch": 0.5, "Merger/Acquisition": 0.5}),
    }

    def run(rule_name, head_name, policy_name):
        policy, class_min = policies[policy_name]
        pred, tiers = [], []
        for i, dec in enumerate(decisions[rule_name]):
            if dec is not None:
                pred.append(dec.event_type)
                tiers.append(alert_tier(dec.source, dec.event_type, confirmed))
                continue
            if i not in heads[head_name]:
                pred.append("Other")
                tiers.append("none")
                continue
            r = _guard_earnings(_result(heads[head_name][i], "head"), texts[i])
            if r.confidence < class_min.get(r.event_type, 0.0):
                r = ClassResult("Other", r.probabilities, r.confidence, "head:abstain")
            r = _select(r, zs.get(i), policy)
            pred.append(r.event_type)
            tiers.append(alert_tier(r.method, r.event_type, confirmed))
        return pred, tiers

    results = []
    for rule_name, head_name, policy_name in itertools.product(RULE_VARIANTS, heads, policies):
        pred, tiers = run(rule_name, head_name, policy_name)
        row = {"rules": rule_name, "head": head_name, "policy": policy_name, "all": scores(pred, y)}
        for s in ("human", "fresh"):
            idx = [i for i, it in enumerate(items) if it["set"] == s]
            row[s] = scores([pred[i] for i in idx], [y[i] for i in idx])
        conf = [p == t for p, t, tier in zip(pred, y, tiers, strict=True) if tier == "confirmed" and p != "Other"]
        row["confirmed_tier"] = {"alerts": len(conf), "correct": sum(conf),
                                 "precision": round(sum(conf) / max(1, len(conf)), 4),
                                 "ci95": wilson(sum(conf), len(conf))}
        results.append(row)
    results.sort(key=lambda r: -r["all"]["macro_f1"])
    print(f"{'rules':4s} {'head':16s} {'policy':14s}  acc    mF1    alertP  PL p/t  MA p/t  CE tp/p/t  Oth tp/t  conf")
    for r in results:
        a = r["all"]
        print(f"{r['rules']:4s} {r['head']:16s} {r['policy']:14s}  {a['accuracy']:.3f}  {a['macro_f1']:.3f}  "
              f"{a['alert_precision']:.3f}  {a['Product Launch']['pred']:>2}/{a['Product Launch']['true']:<3} "
              f"{a['Merger/Acquisition']['pred']:>2}/{a['Merger/Acquisition']['true']:<3} "
              f"{a['Credit Event']['tp']}/{a['Credit Event']['pred']}/{a['Credit Event']['true']:<4} "
              f"{a['Other']['tp']:>3}/{a['Other']['true']:<4} "
              f"{r['confirmed_tier']['correct']}/{r['confirmed_tier']['alerts']}", flush=True)
    out = {"run_at": datetime.now(UTC).isoformat(), "n_items": len(items), "folds": FOLDS,
           "note": "development data (all 478 human labels, incl. the spent fresh set); 5-fold CV for heads trained "
                   "with human labels. Not a final result: the chosen variant is validated on a new fresh set.",
           "per_rule_precision": rule_report, "train_v3": td.describe(data), "results": results}
    tag = "" if ENCODER == "BAAI/bge-base-en-v1.5" else "_" + ENCODER.split("/")[-1]
    out["encoder"] = ENCODER
    path = ROOT / "docs" / "results" / f"round3_experiment{tag}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
