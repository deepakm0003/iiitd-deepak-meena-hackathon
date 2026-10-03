"""Weak-class policy experiment on the human gold DEV split (data/gold/human_check.jsonl).

Simulates the deployed pipeline (8-K items and rules, head, Earnings guard, selection with the zero-shot
verifier) with per-class verification settings and an optional extra rule, and reports dev metrics only.
Run on the GPU server: python scripts/weak_class_experiment.py
"""

import json
import re
import sys
from pathlib import Path

from sklearn.metrics import f1_score

from tripwire.config import load_yaml
from tripwire.factory import build_store
from tripwire.nlp.classifier import EventClassifier, _result
from tripwire.nlp.engine import _guard_earnings, classifier_text
from tripwire.nlp.events import EventRules
from tripwire.nlp.filing_lead import with_filing_leads
from tripwire.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
WEAK = ["Credit Event", "Geopolitical", "Regulatory/Legal"]
# Candidate rule: a regulator's own action (rules, guidance, approvals, enforcement) is Regulatory/Legal.
REGULATOR_ACTION = re.compile(
    r"\b(agencies|regulators?|federal reserve board|fdic|occ|cfpb|sec|ftc|fda|rbi|ecb)\b[^.]{0,80}\b("
    r"seek comment|proposed? (rule|guidance)|final rule|issues? (guidance|rules?|statement)|"
    r"regulatory burden|announces? approval|approves?|enforcement action|terminat(es|ion of) enforcement)",
    re.IGNORECASE)


def main() -> int:
    settings = get_settings()
    store = build_store(settings)
    lines = (ROOT / "data/gold/human_check.jsonl").read_text(encoding="utf-8").splitlines()
    gold = [json.loads(line) for line in lines if line.strip()]
    keys = {g["key"] for g in gold}
    wanted = [d for d in store.iter_documents() if d.dedup_key in keys]
    docs = {d.dedup_key: d for d in with_filing_leads(store, wanted)}
    items = [g for g in gold if g["split"] == "dev" and g["key"] in docs]
    rules = EventRules()
    texts = [classifier_text(docs[g["key"]]) for g in items]
    full = [f"{docs[g['key']].title}. {docs[g['key']].lead}" for g in items]
    decisions = [rules.decide(rules.evidence(docs[g["key"]])) for g in items]
    clf = EventClassifier()
    need = [i for i, (t, d) in enumerate(zip(texts, decisions, strict=True)) if d is None and t]
    heads = dict(zip(need, clf.predict([texts[i] for i in need]), strict=True))
    zss = dict(zip(need, clf.predict_zero_shot([texts[i] for i in need]), strict=True))
    cfg = load_yaml("models.yaml")["event_classifier"]
    verify, base_vmin, min_p = set(cfg["verify"]["classes"]), cfg["verify"]["min_p"], cfg["min_confidence"]

    def run(vmin_by_class=None, ml_disabled=(), regulator_rule=False):
        vmin_by_class = vmin_by_class or {}
        out = []
        for i, dec in enumerate(decisions):
            if regulator_rule and REGULATOR_ACTION.search(full[i]) and (dec is None or dec.event_type == "Other"):
                out.append("Regulatory/Legal")
                continue
            if dec is not None:
                out.append(dec.event_type)
                continue
            if i not in heads:
                out.append("Other")
                continue
            r = _guard_earnings(_result(heads[i].probabilities, "head"), texts[i])
            c = r.event_type
            unverified = c in verify and zss[i].probabilities.get(c, 0.0) < vmin_by_class.get(c, base_vmin)
            out.append("Other" if c == "Other" or r.confidence < min_p or c in ml_disabled or unverified else c)
        return out

    y = [g["event_type"] for g in items]

    def report(name, pred):
        per = {}
        for c in WEAK:
            tp = sum(p == c and t == c for p, t in zip(pred, y, strict=True))
            fp = sum(p == c and t != c for p, t in zip(pred, y, strict=True))
            fn = sum(p != c and t == c for p, t in zip(pred, y, strict=True))
            per[c] = f"TP{tp} FP{fp} FN{fn}"
        acc = sum(p == t for p, t in zip(pred, y, strict=True)) / len(y)
        mf1 = f1_score(y, pred, labels=sorted(set(y)), average="macro", zero_division=0)
        print(f"{name:52s} acc {acc:.3f} macroF1 {mf1:.3f} | " + " | ".join(f"{c[:6]} {v}" for c, v in per.items()))
        return {"accuracy": round(acc, 4), "macro_f1": round(float(mf1), 4), "weak": per}

    results = {"n_dev": len(items)}
    results["current"] = report("current", run())
    for v in (0.3, 0.4, 0.5):
        results[f"credit_geo_vmin_{v}"] = report(f"Credit+Geo verifier >= {v}",
                                                 run({"Credit Event": v, "Geopolitical": v}))
    results["credit_ml_off"] = report("Credit Event only from rules / 8-K items", run(ml_disabled=("Credit Event",)))
    results["credit_geo_ml_off"] = report("Credit + Geo only from rules / 8-K items",
                                          run(ml_disabled=("Credit Event", "Geopolitical")))
    results["regulator_rule"] = report("+ regulator-action rule", run(regulator_rule=True))
    results["credit_ml_off_and_rule"] = report("Credit ML off + regulator rule",
                                               run(ml_disabled=("Credit Event",), regulator_rule=True))
    both = ("Credit Event", "Geopolitical")
    results["credit_geo_ml_off_and_rule"] = report("Credit+Geo ML off + regulator rule",
                                                   run(ml_disabled=both, regulator_rule=True))
    results["credit_geo_vmin_0.4_and_rule"] = report("Credit+Geo verifier >= 0.4 + regulator rule",
                                                     run({c: 0.4 for c in both}, regulator_rule=True))
    out = ROOT / "docs" / "results" / "weak_class_experiment.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
