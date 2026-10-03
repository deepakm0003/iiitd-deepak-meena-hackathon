"""Class-specific verification experiment (human gold DEV split only; the TEST split is locked).

Pipeline under test: 8-K items and rules first; otherwise the MiniLM head proposes candidate classes, a
DeBERTa NLI model verifies them class by class, and the best-supporting source sentence is kept as evidence.

Variants compared on DEV:
  A  current: deberta-v3-base, 11-way zero-shot support for the head's top class, per-class thresholds
  B  same as A with deberta-v3-large
  C  deberta-v3-large, class-specific binary verification: the class definition must be entailed (>= tau) by the
     text or by one of its sentences, and must beat every exclusion hypothesis written from the definitions card
  D  C, and if the head's first candidate is rejected its second candidate is verified the same way
Run on the GPU server: python scripts/verifier_experiment.py
"""

import json
import sys
from pathlib import Path

from sklearn.metrics import f1_score

from tripwire.config import load_yaml
from tripwire.factory import build_store
from tripwire.nlp.classifier import DESCRIPTIONS, EventClassifier, _result
from tripwire.nlp.engine import _guard_earnings, classifier_text
from tripwire.nlp.events import EventRules
from tripwire.nlp.filing_lead import with_filing_leads
from tripwire.nlp.text import split_sentences
from tripwire.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
LARGE = "MoritzLaurer/deberta-v3-large-zeroshot-v2.0"
BASE = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
TEMPLATE = "{}"

# Written from the labelling guide's definitions card (positive definition and explicit exclusions).
VERIFY = {
    "Credit Event": (
        "A company or bank is in financial distress: bankruptcy, a debt default or missed payment, a credit "
        "rating downgrade, a liquidity crisis or a bank run.",
        ["A credit rating was upgraded.",
         "This is about issuing bonds, notes, shares or arranging a loan facility.",
         "This is general advice or commentary about loans, credit cards, debt or insurance.",
         "This is about the economy, a government budget or government finances in general."]),
    "Geopolitical": (
        "Governments are in conflict: war, military action, sanctions, tariffs, export controls or a trade "
        "dispute between countries.",
        ["This is a human-interest story about individual people.",
         "This is about domestic politics, a politician's personality or an election campaign.",
         "This is about a crime or a security incident involving individuals."]),
    "Regulatory/Legal": (
        "There is a lawsuit, a court ruling, a fine, a settlement, a government investigation, a regulator's "
        "rule or guidance, or a regulatory approval.",
        ["This is mainly about one company acquiring or merging with another.",
         "This is opinion or commentary about a stock."]),
    "Merger/Acquisition": (
        "One company is buying, merging with or taking over another company, or spinning off a business.",
        ["This is a partnership or collaboration between companies.",
         "A company is raising money from investors.",
         "This is about a new product or service."]),
    "Natural Disaster/Supply Chain": (
        "A natural disaster or a supply shortage is disrupting people or businesses: a flood, hurricane, "
        "wildfire, earthquake, severe storm or supply-chain disruption.",
        ["A disaster word is used as a figure of speech or as part of a name.",
         "This is about an insurance product."]),
    "Cyber/Operational": (
        "There is a cyberattack, a data breach, a hack, a system outage, a product recall, an accident or a "
        "workers' strike.",
        ["This is general commentary about cybersecurity with no specific incident.",
         "This is a human-interest story about a hero."]),
}


def main() -> int:
    from transformers import pipeline

    settings = get_settings()
    store = build_store(settings)
    lines = (ROOT / "data/gold/human_check.jsonl").read_text(encoding="utf-8").splitlines()
    gold = [json.loads(line) for line in lines if line.strip()]
    dev = [g for g in gold if g["split"] == "dev"]          # TEST is locked: never loaded here
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
    cfg = load_yaml("models.yaml")["event_classifier"]
    verify_set, vmin, vmin_cls = set(cfg["verify"]["classes"]), cfg["verify"]["min_p"], cfg["verify"]["min_p_by_class"]
    min_p = cfg["min_confidence"]
    classes = list(DESCRIPTIONS)

    def eleven_way(model_name):
        zs = pipeline("zero-shot-classification", model=model_name, device=0)
        hyps = [DESCRIPTIONS[c] for c in classes]
        out = {}
        for i in need:
            o = zs(texts[i], candidate_labels=hyps, multi_label=False,
                   hypothesis_template="This financial news item is about {}.")
            out[i] = {classes[hyps.index(lab)]: s for lab, s in zip(o["labels"], o["scores"], strict=True)}
        return out

    zs_base, zs_large = eleven_way(BASE), eleven_way(LARGE)
    nli = pipeline("zero-shot-classification", model=LARGE, device=0)

    def binary(text, hyps):
        o = nli(text, candidate_labels=hyps, multi_label=True, hypothesis_template=TEMPLATE)
        return dict(zip(o["labels"], o["scores"], strict=True))

    cache: dict[tuple[int, str], dict] = {}

    def verify_cls(i, c):
        if (i, c) in cache:
            return cache[(i, c)]
        pos, negs = VERIFY[c]
        units = [texts[i]] + [s for s in split_sentences(texts[i]) if len(s) > 20][:6]
        best_pos, evidence = -1.0, ""
        for u in units:
            p = binary(u, [pos])[pos]
            if p > best_pos:
                best_pos, evidence = p, u
        neg = binary(texts[i], negs)
        cache[(i, c)] = {"pos": best_pos, "neg": max(neg.values()), "neg_hyp": max(neg, key=neg.get),
                         "evidence": evidence[:200]}
        return cache[(i, c)]

    def run(variant, tau=0.5):
        pred, trace = [], []
        for i, dec in enumerate(decisions):
            if dec is not None:
                pred.append(dec.event_type)
                continue
            if i not in heads:
                pred.append("Other")
                continue
            h = heads[i]
            ranked = sorted(h.probabilities.items(), key=lambda kv: -kv[1])
            cands = [c for c, p in ranked[:2] if c != "Other" and p >= min_p]
            if variant in ("A", "B"):
                c = h.event_type
                if c == "Other" or h.confidence < min_p:
                    pred.append("Other")
                    continue
                support = (zs_base if variant == "A" else zs_large)[i].get(c, 0.0)
                pred.append(c if c not in verify_set or support >= vmin_cls.get(c, vmin) else "Other")
                continue
            chosen = "Other"
            for c in cands[: (2 if variant == "D" else 1)]:
                if c not in VERIFY:
                    chosen = c
                    break
                v = verify_cls(i, c)
                if v["pos"] >= tau and v["pos"] > v["neg"]:
                    chosen = c
                    trace.append({"title": items[i]["title"][:90], "class": c, **v})
                    break
            pred.append(chosen)
        return pred, trace

    y = [g["event_type"] for g in items]
    results = {"n_dev": len(items), "n_ml_items": len(need)}

    def report(name, pred):
        acc = sum(p == t for p, t in zip(pred, y, strict=True)) / len(y)
        mf1 = f1_score(y, pred, labels=sorted(set(y)), average="macro", zero_division=0)
        weak = {}
        for c in ("Credit Event", "Geopolitical", "Regulatory/Legal", "Merger/Acquisition"):
            tp = sum(p == c and t == c for p, t in zip(pred, y, strict=True))
            fp = sum(p == c and t != c for p, t in zip(pred, y, strict=True))
            fn = sum(p != c and t == c for p, t in zip(pred, y, strict=True))
            weak[c] = f"TP{tp} FP{fp} FN{fn}"
        print(f"{name:34s} acc {acc:.3f} macroF1 {mf1:.3f} | " + " | ".join(f"{k[:6]} {v}" for k, v in weak.items()),
              flush=True)
        return {"accuracy": round(acc, 4), "macro_f1": round(float(mf1), 4), "weak": weak}

    results["A_current"] = report("A current (base, 11-way)", run("A")[0])
    results["B_large_11way"] = report("B large, 11-way", run("B")[0])
    for tau in (0.5, 0.7, 0.9):
        pc, trace = run("C", tau)
        results[f"C_tau_{tau}"] = report(f"C large class-specific tau {tau}", pc)
        results[f"D_tau_{tau}"] = report(f"D C + 2nd candidate tau {tau}", run("D", tau)[0])
        results[f"C_tau_{tau}_accepted_examples"] = trace[:15]
    out = ROOT / "docs" / "results" / "verifier_experiment.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
