"""Event-classifier retraining experiment, evaluated on the silver labels (data/gold/silver_llm.jsonl).

Protocol (fixed before running):
- Training data never contains an evaluation item or a near-duplicate of one: documents with the same normalised
  title, or MiniLM cosine >= 0.85 to any of the 296 evaluation documents, are excluded.
- Candidates are compared on the DEV split (84 items); the chosen candidate is reported on the TEST split once.
- The whole pipeline is evaluated (8-K items and rules first, then head, Earnings guard, selection with the
  zero-shot verifier), because that is what produces the labels users see.
Run on the GPU server: python scripts/event_head_experiment.py
"""

import json
import os
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from tripwire.config import load_yaml
from tripwire.factory import build_http, build_store
from tripwire.ids import normalize_title
from tripwire.nlp import training_data as td
from tripwire.nlp.classifier import ClassResult, EventClassifier, _result
from tripwire.nlp.engine import _guard_earnings, _select, classifier_text
from tripwire.nlp.events import EventRules
from tripwire.nlp.filing_lead import with_filing_leads
from tripwire.nlp.frame import OPINION
from tripwire.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
CLASSES = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]
MNA_CUES = re.compile(r"\b(acqui|merger|merge|takeover|buyout|tender offer|to buy|bid for|deal for|stake in)", re.I)
GEO_CUES = re.compile(r"\b(tariff|sanction|war\b|china|russia|ukraine|iran|israel|trade (war|deal|talks)|export|"
                      r"embargo|nato|military|geopolit)", re.I)
ENCODERS = os.environ.get("ENCODERS", "sentence-transformers/all-MiniLM-L6-v2,sentence-transformers/all-mpnet-base-v2,"
                                       "BAAI/bge-base-en-v1.5").split(",")


def twitter_v2(path: Path) -> list:
    """Twitter topic examples with the two flawed mappings repaired: 'M&A | Investments' keeps only texts with
    M&A cues, 'Politics' keeps only texts with geopolitical cues (domestic politics is not Geopolitical)."""
    out = []
    for ex in td.twitter_examples(path):
        topic = int(ex.origin.split(":")[1])
        if topic == 13 and not MNA_CUES.search(ex.text):
            continue
        if topic == 16 and not GEO_CUES.search(ex.text):
            continue
        out.append(ex)
    return out


def main() -> int:
    settings = get_settings()
    store, http = build_store(settings), build_http(settings)
    lines = (ROOT / "data/gold/silver_llm.jsonl").read_text(encoding="utf-8").splitlines()
    silver = [json.loads(line) for line in lines if line.strip()]
    skeys = {s["key"] for s in silver}
    ann = {a["dedup_key"]: a for a in store.get_annotations()}
    docs = with_filing_leads(store, store.iter_documents())
    by_key = {d.dedup_key: d for d in docs}

    # ---- exclusion of evaluation items and their near-duplicates
    s_emb = np.array([ann[k]["embedding"] for k in skeys if k in ann and ann[k].get("embedding")], dtype=np.float32)
    s_emb /= np.linalg.norm(s_emb, axis=1, keepdims=True)
    s_titles = {normalize_title(by_key[k].title) for k in skeys if k in by_key}

    def excluded(d) -> bool:
        if d.dedup_key in skeys or normalize_title(d.title) in s_titles:
            return True
        e = ann.get(d.dedup_key, {}).get("embedding")
        if not e:
            return False
        v = np.asarray(e, dtype=np.float32)
        return float((s_emb @ (v / np.linalg.norm(v))).max()) >= 0.85

    # ---- training sets
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    edgar = td.edgar_examples(store, utc("2023-01-01"), utc("2024-12-31"))
    tw_path = td.download_twitter_topic(http, "train")
    base = td.balance(edgar + td.twitter_examples(tw_path) + td.seed_examples(), per_class=64)

    in_domain, other = [], []
    for d in docs:
        if d.source == "edgar" or excluded(d):
            continue
        a = ann.get(d.dedup_key)
        if not a:
            continue
        text = classifier_text(d)
        if a["event_method"].startswith("rule:"):
            in_domain.append(td.Example(text[:td.MAX_CHARS], a["event_type"], f"rule:{a['event_method'][5:]}"))
        elif OPINION.search(d.title):
            other.append(td.Example(text[:td.MAX_CHARS], "Other", "opinion_headline"))
    random.Random(3).shuffle(other)
    v2_pool = edgar + twitter_v2(tw_path) + td.seed_examples() + in_domain + other[:400]
    v2 = td.balance(v2_pool, per_class=150)
    # v3: in-domain first. balance() keeps "seed"-origin examples before the rest, so in-domain rule examples and
    # opinion-headline Others are given that priority; Twitter only fills the remaining slots.
    promoted = [td.Example(e.text, e.label, "seed") for e in in_domain + other[:400]]
    v3 = td.balance(edgar + twitter_v2(tw_path) + td.seed_examples() + promoted, per_class=150)
    print("excluded near-duplicates; in-domain rule examples:", len(in_domain), "opinion Other:", len(other))
    print("base:", td.describe(base))
    print("v2:  ", td.describe(v2))
    print("v3:  ", td.describe(v3))

    # ---- evaluation items: pipeline inputs and cached zero-shot probabilities
    rules = EventRules()
    items = [s for s in silver if s["key"] in by_key]
    texts = [classifier_text(by_key[s["key"]]) for s in items]
    decisions = [rules.decide(rules.evidence(by_key[s["key"]])) for s in items]
    clf = EventClassifier()
    need = [i for i, (t, dec) in enumerate(zip(texts, decisions, strict=True)) if dec is None and t]
    zs = dict(zip(need, clf.predict_zero_shot([texts[i] for i in need]), strict=True))
    cfg = load_yaml("models.yaml")["event_classifier"]
    policy = {"min_confidence": cfg["min_confidence"], "verify_classes": set(cfg["verify"]["classes"]),
              "verifier_min_p": cfg["verify"]["min_p"]}

    def pipeline(head_probs) -> list[str]:
        out = []
        for i, dec in enumerate(decisions):
            if dec is not None:
                out.append(dec.event_type)
            elif not texts[i]:
                out.append("Other")
            else:
                r = _guard_earnings(_result(head_probs[i], "head"), texts[i])
                out.append(_select(ClassResult(r.event_type, r.probabilities, r.confidence, r.method),
                                   zs.get(i), policy).event_type)
        return out

    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score

    def scores(pred, split):
        idx = [i for i, s in enumerate(items) if s["split"] == split]
        y = [items[i]["event_type"] for i in idx]
        p = [pred[i] for i in idx]
        present = sorted(set(y))
        assigned = [(a, b) for a, b in zip(p, y, strict=True) if a != "Other"]
        return {"n": len(idx), "accuracy": round(sum(a == b for a, b in zip(p, y, strict=True)) / len(y), 4),
                "macro_f1": round(float(f1_score(y, p, labels=present, average="macro", zero_division=0)), 4),
                "non_other_precision": round(sum(a == b for a, b in assigned) / max(1, len(assigned)), 4),
                "non_other_recall": round(sum(a == b for a, b in zip(p, y, strict=True) if b != "Other")
                                          / max(1, sum(b != "Other" for b in y)), 4)}

    # current production head as the reference
    current = clf._predict_head(texts)
    results = {"current_head": {"dev": scores(pipeline([r.probabilities for r in current]), "dev"),
                                "test": scores(pipeline([r.probabilities for r in current]), "test")}}
    print("current_head", results["current_head"])
    for enc_name in ENCODERS:
        enc = SentenceTransformer(enc_name, device="cuda")

        def embed(t, enc=enc):
            return enc.encode(t, batch_size=64, normalize_embeddings=True, show_progress_bar=False)

        x_eval = embed(texts)
        sets = {"base": base, "v2": v2, "v3": v3}
        for data_name in os.environ.get("VARIANTS", "base,v2").split(","):
            data = sets[data_name]
            lr = LogisticRegression(max_iter=3000, class_weight="balanced", C=2.0)
            lr.fit(embed([e.text for e in data]), [e.label for e in data])
            probs = [dict(zip(lr.classes_, row.tolist(), strict=True)) for row in lr.predict_proba(x_eval)]
            pred = pipeline(probs)
            key = f"{enc_name.split('/')[-1]}|{data_name}"
            results[key] = {"dev": scores(pred, "dev"), "test": scores(pred, "test")}
            print(key, "DEV", results[key]["dev"])
    out = ROOT / "var" / f"event_head_experiment_{os.environ.get('VARIANTS', 'base,v2').replace(',', '_')}.json"
    out.write_text(json.dumps({"results": results, "train": {"base": td.describe(base), "v2": td.describe(v2)}},
                              indent=2), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
