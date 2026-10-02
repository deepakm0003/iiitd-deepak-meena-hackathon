"""Gold-set evaluation of the event pipeline (human labels in data/gold/gold.jsonl).

The candidates were sampled in strata (tripwire.gold.sample_stratified), so two kinds of numbers are reported
and never mixed up:

1. Population estimates, valid for the whole corpus:
   - precision of class c = share correct among items in stratum "pred:c" (a random sample of everything the
     pipeline put in c; for small classes the stratum is the whole class);
   - recall of class c = weighted true positives / weighted true c, each item weighted by
     stratum_population / items sampled from its stratum (inverse sampling probability).
   Wilson 95% intervals for precision; recall intervals are not given (weights make them unreliable at n < 300).
2. On-sample metrics ("as sampled"): per-class P/R/F1, support, macro- and weighted-F1, confusion matrix. They
   describe the labelled sample, which over-represents rare classes by design.

Only the test split (75%, fixed by key hash) is used for metrics; the dev split (25%) is for choosing thresholds.
"""

import math
from collections import Counter


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def on_sample(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true) | set(y_pred))
    per_class, f1s, weights = {}, [], []
    for c in labels:
        tp = sum(t == c and p == c for t, p in zip(y_true, y_pred, strict=True))
        n_pred, support = y_pred.count(c), y_true.count(c)
        prec = tp / n_pred if n_pred else None
        rec = tp / support if support else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0
        per_class[c] = {"precision": _r(prec), "recall": _r(rec), "f1": round(f1, 4), "support": support,
                        "predicted": n_pred}
        if support:
            f1s.append(f1)
            weights.append(support)
    confusion = {t: dict(Counter(p for tt, p in zip(y_true, y_pred, strict=True) if tt == t)) for t in labels}
    return {
        "n": len(y_true), "accuracy": round(sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / len(y_true), 4),
        "macro_f1": round(sum(f1s) / len(f1s), 4),
        "weighted_f1": round(sum(f * w for f, w in zip(f1s, weights, strict=True)) / sum(weights), 4),
        "classes_with_support": len(f1s), "per_class": per_class, "confusion_true_by_pred": confusion,
    }


def population(rows: list[dict], classes: list[str]) -> dict:
    """rows: {"stratum", "stratum_population", "gold", "pred"}. Precision from pred strata, recall weighted."""
    sampled = Counter(r["stratum"] for r in rows)
    weight = {s: next(r["stratum_population"] for r in rows if r["stratum"] == s) / n for s, n in sampled.items()}
    out = {}
    for c in classes:
        stratum = [r for r in rows if r["stratum"] == f"pred:{c}"]
        k = sum(r["gold"] == c for r in stratum)
        tp_w = sum(weight[r["stratum"]] for r in rows if r["gold"] == c and r["pred"] == c)
        true_w = sum(weight[r["stratum"]] for r in rows if r["gold"] == c)
        out[c] = {
            "precision": _r(k / len(stratum)) if stratum else None, "precision_ci95": wilson(k, len(stratum)),
            "precision_n": len(stratum), "stratum_population": stratum[0]["stratum_population"] if stratum else 0,
            "census": bool(stratum) and len(stratum) == stratum[0]["stratum_population"],
            "recall_weighted": _r(tp_w / true_w) if true_w else None,
            "true_items_found": sum(r["gold"] == c for r in rows),
        }
    return out


def selective(rows: list[dict], min_p: float, verify: set[str], verifier_min_p: float) -> list[str]:
    """Re-apply the selection policy to stored head / zero-shot probabilities (rows from ML-classified items)."""
    from tripwire.eval.event_selective import apply_policy

    return [apply_policy(r["head"], r.get("zs"), min_p, verify, verifier_min_p) for r in rows]


def threshold_sweep(rows: list[dict], verify: set[str]) -> list[dict]:
    """Coverage / precision / recall / F1 / false-positive rate of non-Other ML labels at each threshold pair."""
    y = [r["gold"] for r in rows]
    out = []
    for min_p in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
        for vmin in (None, 0.05, 0.10, 0.20, 0.30):
            pred = selective(rows, min_p, verify if vmin is not None else set(), vmin or 0.0)
            assigned = [(p, t) for p, t in zip(pred, y, strict=True) if p != "Other"]
            tp = sum(p == t for p, t in assigned)
            positives = sum(t != "Other" for t in y)
            negatives = len(y) - positives
            prec = tp / len(assigned) if assigned else None
            rec = tp / positives if positives else None
            out.append({
                "min_p": min_p, "verifier_min_p": vmin, "coverage": round(len(assigned) / len(y), 4),
                "precision": _r(prec), "recall": _r(rec),
                "f1": round(2 * prec * rec / (prec + rec), 4) if prec and rec else 0.0,
                "false_positive_rate": round(sum(t == "Other" for _, t in assigned) / negatives, 4)
                if negatives else None,
            })
    return out


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)
