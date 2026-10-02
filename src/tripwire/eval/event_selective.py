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
    tp = sum(p == t for p, t in assigned)
    positives = sum(t != "Other" for t in y)
    negatives = len(y) - positives
    prec = tp / len(assigned) if assigned else None
    rec = tp / max(1, positives)
    return {
        "macro_f1": round(float(f1_score(y, pred, labels=present, average="macro", zero_division=0)), 4),
        "non_other_precision": round(prec, 4) if prec is not None else None,
        "non_other_recall": round(rec, 4),
        "non_other_f1": round(2 * prec * rec / (prec + rec), 4) if prec and rec else 0.0,
        "coverage": round(len(assigned) / len(y), 4),
        "false_positive_rate": round(sum(t == "Other" for _, t in assigned) / negatives, 4) if negatives else None,
        "n_assigned": len(assigned),
    }


def calibration(y: list[str], heads: list[dict[str, float]]) -> dict:
    """Is the head's top-1 probability a probability? ECE (10 equal-count bins) before and after temperature
    scaling fitted on the same split (a diagnostic: thresholds compare probabilities, so they mean what they
    say only if the probabilities are calibrated)."""
    import math

    def scaled(h, t):
        z = {c: math.exp(math.log(max(v, 1e-9)) / t) for c, v in h.items()}
        total = sum(z.values())
        return {c: v / total for c, v in z.items()}

    def nll(t):
        return -sum(math.log(max(scaled(h, t).get(c, 1e-9), 1e-9)) for h, c in zip(heads, y, strict=True)) / len(y)

    def ece(t):
        conf = []
        for h, c in zip(heads, y, strict=True):
            q = scaled(h, t)
            top = max(q, key=q.get)
            conf.append((q[top], top == c))
        conf.sort()
        n, out = len(conf), 0.0
        for b in range(10):
            part = conf[b * n // 10:(b + 1) * n // 10]
            if part:
                out += len(part) / n * abs(sum(x for x, _ in part) / len(part) - sum(ok for _, ok in part) / len(part))
        return round(out, 4)

    grid = [round(0.3 + 0.05 * i, 2) for i in range(55)]
    best = min(grid, key=nll)
    return {"ece_raw": ece(1.0), "temperature": best, "ece_temperature_scaled": ece(best),
            "nll_raw": round(nll(1.0), 4), "nll_scaled": round(nll(best), 4)}


def sweep(y, heads, zss, verify: set[str]) -> list[dict]:
    rows = []
    for min_p in (0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
        for vmin in (None, 0.05, 0.10, 0.15, 0.20, 0.30):
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
        "calibration_head_top1": calibration(y, heads),
    }
