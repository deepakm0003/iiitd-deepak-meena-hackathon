"""Gold-set metrics: stratified population estimates and on-sample metrics (synthetic labels, for the maths only)."""

import pytest

from tripwire.eval import gold_eval as ge


def test_wilson_interval_is_sensible():
    lo, hi = ge.wilson(30, 35)
    assert lo < 30 / 35 < hi and lo > 0.6 and hi < 0.97
    assert ge.wilson(0, 0) is None


def test_on_sample_metrics_ignore_absent_classes_in_macro_f1():
    y_true = ["A", "A", "B", "B", "Other"]
    y_pred = ["A", "B", "B", "B", "Other"]
    m = ge.on_sample(y_true, y_pred)
    assert m["classes_with_support"] == 3
    assert m["per_class"]["A"]["precision"] == 1.0 and m["per_class"]["A"]["recall"] == 0.5
    assert m["per_class"]["B"]["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["confusion_true_by_pred"]["A"] == {"A": 1, "B": 1}


def test_population_precision_from_its_stratum_and_weighted_recall():
    rows = (
        # pred:A stratum, 10 sampled of 10 (census): 8 right
        [{"stratum": "pred:A", "stratum_population": 10, "gold": "A", "pred": "A"}] * 8
        + [{"stratum": "pred:A", "stratum_population": 10, "gold": "Other", "pred": "A"}] * 2
        # pred:Other stratum, 5 sampled of 100: one is really A (a miss that stands for 20 items)
        + [{"stratum": "pred:Other", "stratum_population": 100, "gold": "A", "pred": "Other"}]
        + [{"stratum": "pred:Other", "stratum_population": 100, "gold": "Other", "pred": "Other"}] * 4
    )
    pop = ge.population(rows, ["A", "Other"])
    assert pop["A"]["precision"] == 0.8 and pop["A"]["census"] is True
    assert pop["A"]["recall_weighted"] == pytest.approx(8 / (8 + 20), abs=1e-4)   # 8 found, ~20 missed


def test_threshold_sweep_trades_coverage_for_precision():
    rows = [{"gold": "A", "head": {"A": 0.9, "Other": 0.1}, "zs": {"A": 0.8}},
            {"gold": "Other", "head": {"A": 0.35, "Other": 0.30}, "zs": {"A": 0.02}},
            {"gold": "A", "head": {"A": 0.32, "Other": 0.30}, "zs": {"A": 0.5}},
            {"gold": "Other", "head": {"Other": 0.9, "A": 0.1}, "zs": {"A": 0.1}}]
    sweep = {(r["min_p"], r["verifier_min_p"]): r for r in ge.threshold_sweep(rows, {"A"})}
    loose, verified = sweep[(0.1, None)], sweep[(0.1, 0.1)]
    assert loose["coverage"] == 0.75 and loose["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert verified["precision"] == 1.0 and verified["false_positive_rate"] == 0.0
