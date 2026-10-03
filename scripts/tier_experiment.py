"""Precision per decision source, to define a 'confirmed' alert tier (development data: all 296 human labels).

The original 212-item test split was evaluated once and its result is frozen in docs/IMPROVEMENT_LOG.md; from
here on all 296 human-labelled items are development data, and a fresh out-of-time test set (articles collected
after the model freeze) validates the result. Each non-Other prediction is attributed to its source: an 8-K
item, a named rule, or the ML head (+ verifier); precision is reported per source with a Wilson interval.
Run on the GPU server: python scripts/tier_experiment.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.eval.gold_eval import wilson
from tripwire.factory import build_store
from tripwire.nlp.classifier import EventClassifier, _result
from tripwire.nlp.engine import _guard_earnings, _select, classifier_text
from tripwire.nlp.events import EventRules
from tripwire.nlp.filing_lead import with_filing_leads
from tripwire.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    store = build_store(get_settings())
    lines = (ROOT / "data/gold/human_check.jsonl").read_text(encoding="utf-8").splitlines()
    gold = [json.loads(x) for x in lines if x.strip()]
    keys = {g["key"] for g in gold}
    wanted = [d for d in store.iter_documents() if d.dedup_key in keys]
    docs = {d.dedup_key: d for d in with_filing_leads(store, wanted)}
    items = [g for g in gold if g["key"] in docs]
    rules = EventRules()
    texts = [classifier_text(docs[g["key"]]) for g in items]
    decisions = [rules.decide(rules.evidence(docs[g["key"]])) for g in items]
    clf = EventClassifier()
    need = [i for i, (t, d) in enumerate(zip(texts, decisions, strict=True)) if d is None and t]
    heads = {i: _guard_earnings(_result(r.probabilities, "head"), texts[i])
             for i, r in zip(need, clf.predict([texts[i] for i in need]), strict=True)}
    zss = dict(zip(need, clf.predict_zero_shot([texts[i] for i in need]), strict=True))
    cfg = load_yaml("models.yaml")["event_classifier"]
    policy = {"min_confidence": cfg["min_confidence"], "verify_classes": set(cfg["verify"]["classes"]),
              "verifier_min_p": cfg["verify"]["min_p"], "verifier_min_p_by_class": cfg["verify"]["min_p_by_class"]}
    by_source: dict[str, list[bool]] = defaultdict(list)
    wrong: dict[str, list[str]] = defaultdict(list)
    correct_total = 0
    for i, g in enumerate(items):
        if decisions[i] is not None:
            pred, source = decisions[i].event_type, decisions[i].source.split(":")[0] + (
                ":" + decisions[i].source.split(":")[1] if decisions[i].source.startswith("rule") else "")
        elif i in heads:
            r = _select(heads[i], zss[i], policy)
            pred, source = r.event_type, "ml"
        else:
            pred, source = "Other", "no_text"
        correct_total += pred == g["event_type"]
        if pred != "Other":
            by_source[source].append(pred == g["event_type"])
            if pred != g["event_type"]:
                wrong[source].append(f"pred {pred} / human {g['event_type']}: {g['title'][:80]}")
    out = {"n": len(items), "accuracy_all_296": round(correct_total / len(items), 4), "sources": {}}
    for s, oks in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        k, n = sum(oks), len(oks)
        out["sources"][s] = {"alerts": n, "correct": k, "precision": round(k / n, 4), "ci95": wilson(k, n),
                             "errors": wrong[s][:6]}
        print(f"{s:28s} {k:3d}/{n:<3d} precision {k / n:.3f} CI {wilson(k, n)}", flush=True)
    print("accuracy on all 296 (development data):", out["accuracy_all_296"])
    path = ROOT / "docs" / "results" / "tier_experiment.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
