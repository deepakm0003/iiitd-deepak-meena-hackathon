"""Selective classification for ML event labels: when to accept the head's label, and when to abstain.

The head assigns a class to every input, however unsure. On live data that turned noise into stress-test
inputs (a celebrity feud labelled Geopolitical at p = 0.43). Two measured controls:
  1. a minimum head probability for any ML label;
  2. for the stress-mappable classes (they drive Module B), agreement from an independent model: the
     zero-shot NLI classifier (DeBERTa-v3) must give the class at least `verifier_min_p`.
Thresholds are chosen on the validation split only and reported with per-class precision and recall.
"""

from collections import Counter


def apply_policy(head: dict[str, float], zs: dict[str, float] | None, min_p: float, verify: set[str],
                 verifier_min_p: float) -> str:
    best = max(head, key=head.get)
    if best == "Other" or head[best] < min_p:
        return "Other"
    if best in verify and zs is not None and zs.get(best, 0.0) < verifier_min_p:
        return "Other"
    return best


def per_class(y: list[str], pred: list[str]) -> dict[str, dict]:
    out = {}
    for c in sorted(set(y) | set(pred)):
        tp = sum(p == c and t == c for p, t in zip(pred, y, strict=True))
        n_pred, n_true = sum(p == c for p in pred), sum(t == c for t in y)
        out[c] = {"precision": round(tp / n_pred, 4) if n_pred else None,
                  "recall": round(tp / n_true, 4) if n_true else None, "n_pred": n_pred, "n_true": n_true}
    return out


def summary(y: list[str], pred: list[str]) -> dict:
    from sklearn.metrics import f1_score

    present = sorted(set(y))  # macro-F1 over classes present in the evaluation data only
    assigned = [(p, t) for p, t in zip(pred, y, strict=True) if p != "Other"]
    return {
        "macro_f1": round(float(f1_score(y, pred, labels=present, average="macro", zero_division=0)), 4),
        "non_other_precision": round(sum(p == t for p, t in assigned) / len(assigned), 4) if assigned else None,
        "non_other_recall": round(sum(p == t for p, t in zip(pred, y, strict=True) if t != "Other")
                                  / max(1, sum(t != "Other" for t in y)), 4),
        "n_assigned": len(assigned),
    }


def sweep(y, heads, zss, verify: set[str]) -> list[dict]:
    rows = []
    for min_p in (0.0, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5):
        for vmin in (None, 0.1, 0.2, 0.3):
            pred = [apply_policy(h, z, min_p, verify if vmin is not None else set(), vmin or 0.0)
                    for h, z in zip(heads, zss, strict=True)]
            rows.append({"min_p": min_p, "verifier_min_p": vmin, **summary(y, pred)})
    return rows


def report(y, heads, zss, origins, verify: set[str], min_p: float, verifier_min_p: float) -> dict:
    chosen = [apply_policy(h, z, min_p, verify, verifier_min_p) for h, z in zip(heads, zss, strict=True)]
    shipped = [max(h, key=h.get) for h in heads]
    return {
        "data": {"n": len(y), "by_label": dict(Counter(y).most_common()),
                 "by_origin": dict(Counter(o.split(":")[0] for o in origins).most_common()),
                 "note": "validation split (twitter-financial-news-topic valid + 8-K filings 2025H1); it has no "
                         "Credit Event, Cyber/Operational, Natural Disaster or Product Launch examples, so their "
                         "precision is measured later on the human gold set."},
        "policy": {"min_head_p": min_p, "verify_classes": sorted(verify), "verifier": "zero-shot NLI",
                   "verifier_min_p": verifier_min_p},
        "before": {**summary(y, shipped), "per_class": per_class(y, shipped)},
        "after": {**summary(y, chosen), "per_class": per_class(y, chosen)},
        "sweep": sweep(y, heads, zss, verify),
    }
