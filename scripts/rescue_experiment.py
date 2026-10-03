"""Zero-shot rescue for abstentions + selective precision, on the human gold DEV split only (TEST is locked).

1. Rescue: when the head abstains or says Other, the independent zero-shot NLI classifier may assign its own top
   class if it is confident enough (tau). Compared with the current pipeline at several tau.
2. Selective precision: every non-Other prediction gets a confidence (8-K item 0.95, rule 0.90, ML = head
   probability x zero-shot support); precision and coverage of "alerts" above each confidence threshold.
Run on the GPU server: python scripts/rescue_experiment.py
"""

import json
import sys
from pathlib import Path

from sklearn.metrics import f1_score

from tripwire.config import load_yaml
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
    dev = [json.loads(x) for x in lines if x.strip() and json.loads(x)["split"] == "dev"]
    keys = {g["key"] for g in dev}
    wanted = [d for d in store.iter_documents() if d.dedup_key in keys]
    docs = {d.dedup_key: d for d in with_filing_leads(store, wanted)}
    items = [g for g in dev if g["key"] in docs]
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
    y = [g["event_type"] for g in items]

    def run(tau=None, rescue_classes=None):
        pred, conf = [], []
        for i, dec in enumerate(decisions):
            if dec is not None:
                pred.append(dec.event_type)
                conf.append(dec.confidence)
                continue
            if i not in heads:
                pred.append("Other")
                conf.append(0.0)
                continue
            r = _select(heads[i], zss[i], policy)
            z = zss[i].probabilities
            if r.event_type == "Other" and tau is not None:
                top = max(z, key=z.get)
                if top != "Other" and z[top] >= tau and (rescue_classes is None or top in rescue_classes):
                    pred.append(top)
                    conf.append(z[top])
                    continue
            pred.append(r.event_type)
            conf.append(r.confidence * z.get(r.event_type, 0.0) if r.event_type != "Other" else 0.0)
        return pred, conf

    def report(name, pred):
        acc = sum(p == t for p, t in zip(pred, y, strict=True)) / len(y)
        mf1 = f1_score(y, pred, labels=sorted(set(y)), average="macro", zero_division=0)
        rec = {}
        for c in ("Credit Event", "Macroeconomic"):
            tp = sum(p == c and t == c for p, t in zip(pred, y, strict=True))
            fp = sum(p == c and t != c for p, t in zip(pred, y, strict=True))
            rec[c] = f"TP{tp}/{y.count(c)} FP{fp}"
        print(f"{name:44s} acc {acc:.3f} macroF1 {mf1:.3f} | " + " | ".join(f"{k[:6]} {v}" for k, v in rec.items()),
              flush=True)
        return {"accuracy": round(acc, 4), "macro_f1": round(float(mf1), 4), **rec}

    out = {"n_dev": len(items), "current": report("current", run()[0])}
    for tau in (0.4, 0.5, 0.6, 0.7):
        out[f"rescue_any_{tau}"] = report(f"rescue, any class, tau {tau}", run(tau)[0])
        out[f"rescue_cm_{tau}"] = report(f"rescue, Credit+Macro only, tau {tau}",
                                         run(tau, {"Credit Event", "Macroeconomic"})[0])
    # selective precision of alerts (non-Other predictions) for the current pipeline
    pred, conf = run()
    alerts = sorted(((c, p == t) for p, t, c in zip(pred, y, conf, strict=True) if p != "Other"), reverse=True)
    curve = []
    for k in range(1, len(alerts) + 1):
        hits = sum(ok for _, ok in alerts[:k])
        curve.append({"min_confidence": round(alerts[k - 1][0], 4), "alerts": k, "precision": round(hits / k, 4)})
    out["selective_curve_current"] = curve
    print("selective (current): " + ", ".join(f"{c['alerts']}@{c['min_confidence']}={c['precision']}"
                                              for c in curve[::5]), flush=True)
    path = ROOT / "docs" / "results" / "rescue_experiment.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
