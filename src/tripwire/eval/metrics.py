"""Classification metrics with bootstrap 95% confidence intervals (every MEASURED number carries n and a CI)."""

import random
from collections import Counter
from collections.abc import Callable, Sequence


def accuracy(y_true: Sequence, y_pred: Sequence) -> float:
    return sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / max(1, len(y_true))


def per_class(y_true: Sequence, y_pred: Sequence, labels: Sequence) -> dict[str, dict[str, float]]:
    out = {}
    for label in labels:
        tp = sum(t == label and p == label for t, p in zip(y_true, y_pred, strict=True))
        fp = sum(t != label and p == label for t, p in zip(y_true, y_pred, strict=True))
        fn = sum(t == label and p != label for t, p in zip(y_true, y_pred, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[str(label)] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    return out


def macro_f1(y_true: Sequence, y_pred: Sequence, labels: Sequence | None = None) -> float:
    labels = labels or sorted(set(y_true))
    scores = per_class(y_true, y_pred, labels)
    present = [s["f1"] for s in scores.values() if s["support"] > 0]
    return sum(present) / max(1, len(present))


def confusion(y_true: Sequence, y_pred: Sequence) -> dict[str, dict[str, int]]:
    table: dict[str, Counter] = {}
    for t, p in zip(y_true, y_pred, strict=True):
        table.setdefault(str(t), Counter())[str(p)] += 1
    return {t: dict(c) for t, c in table.items()}


def bootstrap_ci(
    y_true: Sequence, y_pred: Sequence, metric: Callable, n_boot: int = 1000, seed: int = 11
) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(y_true)
    if n == 0:
        return (0.0, 0.0)
    values = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        values.append(metric([y_true[i] for i in idx], [y_pred[i] for i in idx]))
    values.sort()
    return (round(values[int(0.025 * n_boot)], 4), round(values[int(0.975 * n_boot) - 1], 4))


def summary(y_true: Sequence, y_pred: Sequence, labels: Sequence | None = None) -> dict:
    labels = labels or sorted(set(y_true) | set(y_pred))
    return {
        "n": len(y_true),
        "accuracy": round(accuracy(y_true, y_pred), 4),
        "accuracy_ci95": bootstrap_ci(y_true, y_pred, accuracy),
        "macro_f1": round(macro_f1(y_true, y_pred, labels), 4),
        "macro_f1_ci95": bootstrap_ci(y_true, y_pred, lambda t, p: macro_f1(t, p, labels)),
        "per_class": {k: {m: round(v, 4) for m, v in s.items()} for k, s in per_class(y_true, y_pred, labels).items()},
        "confusion": confusion(y_true, y_pred),
    }
