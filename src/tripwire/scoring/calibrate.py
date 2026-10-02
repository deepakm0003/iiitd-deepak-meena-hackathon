"""Calibrate the Impact model on the calibration period and validate it out-of-time (reported regardless).

Timeline (no information flows backwards):
  calibration  2023-01-01 .. 2025-06-30   H table, percentile scale, isotonic P(large move), weights
     inner fit   ..2024-06-30            fitted weights are estimated here...
     inner check 2024-07-01..2025-06-30  ...and expert vs fitted is DECIDED here, before any test data is used
  test         2025-07-01 ..             frozen model scored once; baselines and ablations alongside
Target: |SCAR[0,+1]| of 8-K events (firm-specific, exact timestamps). Macro and social events have no single
stock to test and are not part of this validation (stated in the report).
"""

import json
import random
from datetime import UTC, date, datetime

from tripwire.nlp.events import EventRules
from tripwire.scoring import records as rec
from tripwire.scoring.event_study import study
from tripwire.scoring.impact import (
    FACTORS,
    ImpactModel,
    blend_weights,
    fit_isotonic,
    fit_weights,
    h_table,
    identifiable,
    tail_counts,
)

# H is measured only on events whose type is known without the ML layer (8-K item map, high-precision rules):
# ML labels on routine filings ("Item 8.01 Other Events" guessed as Credit Event) would put noise into H.
DETERMINISTIC_METHODS = ("8k_item", "rule")


def _spearman(x: list[float], y: list[float]) -> float:
    from scipy.stats import spearmanr

    return float(spearmanr(x, y).statistic) if len(x) > 2 else float("nan")


def _spearman_ci(x, y, n_boot: int = 1000, seed: int = 5) -> tuple[float, float]:
    rng = random.Random(seed)
    n, values = len(x), []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        values.append(_spearman([x[i] for i in idx], [y[i] for i in idx]))
    values.sort()
    return (round(values[int(0.025 * n_boot)], 4), round(values[int(0.975 * n_boot) - 1], 4))


def _auc(scores: list[float], labels: list[bool]) -> float | None:
    from sklearn.metrics import roc_auc_score

    return round(float(roc_auc_score(labels, scores)), 4) if len(set(labels)) == 2 else None


def _pr_auc(scores: list[float], labels: list[bool]) -> float | None:
    from sklearn.metrics import average_precision_score

    return round(float(average_precision_score(labels, scores)), 4) if len(set(labels)) == 2 else None


def _calibration(probs: list[float], labels: list[bool]) -> dict:
    """Brier score and expected calibration error (10 equal-count bins) of P(large move)."""
    n = len(probs)
    brier = sum((p - y) ** 2 for p, y in zip(probs, labels, strict=True)) / n
    order = sorted(range(n), key=lambda i: probs[i])
    bins, ece = [], 0.0
    for b in range(10):
        idx = order[b * n // 10:(b + 1) * n // 10]
        if not idx:
            continue
        mean_p = sum(probs[i] for i in idx) / len(idx)
        rate = sum(labels[i] for i in idx) / len(idx)
        ece += len(idx) / n * abs(mean_p - rate)
        bins.append({"mean_predicted": round(mean_p, 4), "observed": round(rate, 4), "n": len(idx)})
    return {"brier": round(brier, 4), "brier_base_rate": round(sum(labels) / n * (1 - sum(labels) / n), 4),
            "ece": round(ece, 4), "reliability": bins}


def evaluate(model: ImpactModel, rows: list[dict]) -> dict:
    impacts = [model.impact(model.adjusted(r["factors"], r["relevance"])) for r in rows]
    target = [r["abs_scar"] for r in rows]
    large = [r["large"] for r in rows]
    probs = [model.p_large_move(v) for v in impacts]
    buckets = []
    for lo, hi in ((1, 4), (4, 7), (7, 8.5), (8.5, 10.01)):
        idx = [i for i, v in enumerate(impacts) if lo <= v < hi]
        buckets.append({
            "impact": f"{lo}-{min(hi, 10)}", "n": len(idx),
            "mean_abs_scar": round(sum(target[i] for i in idx) / len(idx), 3) if idx else None,
            "share_large_move": round(sum(large[i] for i in idx) / len(idx), 3) if idx else None,
        })
    triggered = [i for i, v in enumerate(impacts) if v >= 7]
    return {
        "n": len(rows),
        "spearman": round(_spearman(impacts, target), 4),
        "spearman_ci95": _spearman_ci(impacts, target),
        "auc_large_move": _auc(impacts, large),
        "pr_auc_large_move": _pr_auc(impacts, large),
        "probability": _calibration(probs, large) if None not in probs else None,
        "base_rate_large_move": round(sum(large) / max(1, len(large)), 4),
        "trigger_precision_impact_ge_7": round(sum(large[i] for i in triggered) / len(triggered), 4)
        if triggered else None,
        "n_triggered": len(triggered),
        "buckets": buckets,
    }


def _single_factor(rows: list[dict], factor: str) -> dict:
    scores = [r["factors"][factor] for r in rows]
    target = [r["abs_scar"] for r in rows]
    return {"spearman": round(_spearman(scores, target), 4), "spearman_ci95": _spearman_ci(scores, target),
            "auc_large_move": _auc(scores, [r["large"] for r in rows])}


def run(store, cal_start: date = date(2023, 1, 1), inner_split: date = date(2024, 6, 30),
        cal_end: date = date(2025, 6, 30), test_start: date = date(2025, 7, 1)) -> tuple[ImpactModel, dict, list]:
    from tripwire.market.prices import MARKET_TICKERS
    from tripwire.universe import load_universe

    tickers = [c.ticker for c in load_universe()]
    prices = {t: {b.date: b.adj_close for b in store.get_prices(t)} for t in [*tickers, *MARKET_TICKERS]}
    prices = {t: p for t, p in prices.items() if p}
    returns_, study_stats = study(rec.filing_events(store), prices)
    by_raw = {int(r.event_key): r for r in returns_}

    importance = rec.entity_importance(store, tickers, (cal_start, cal_end))
    records = rec.build_records(store, importance, EventRules())
    for r in records:
        studied = [by_raw[i] for i in r["doc_ids"] if i in by_raw]
        r["abs_scar"] = abs(studied[0].scar) if studied else None
        r["large"] = studied[0].large if studied else None
        r["scar"] = studied[0].scar if studied else None
        r["day"] = r["first_seen"].date() if isinstance(r["first_seen"], datetime) else r["first_seen"]

    in_cal = [r for r in records if cal_start <= r["day"] <= cal_end]
    cal_studied = [r for r in in_cal if r["abs_scar"] is not None]
    by_type: dict[str, list[float]] = {}
    for r in cal_studied:
        if r["event_method"].startswith(DETERMINISTIC_METHODS):
            by_type.setdefault(r["event_type"], []).append(r["abs_scar"])
    severity = EventRules()
    class_priors = {c: severity.prior(c) for c in severity.severity_classes()}
    table = h_table(by_type, class_priors)
    for r in records:
        r["factors"]["H_historical_reaction"] = table.get(r["event_type"], table.get("__default__", 0.5))

    def make(weights, source, corpus_rows, iso_rows=None):
        tmp = ImpactModel(weights=weights, h_table=table, calibration_adjusted=[], weights_source=source,
                          calibration_period=(cal_start.isoformat(), cal_end.isoformat()))
        tmp.calibration_adjusted = sorted(tmp.adjusted(r["factors"], r["relevance"]) for r in corpus_rows)
        if iso_rows:
            tmp.isotonic = fit_isotonic([tmp.impact(tmp.adjusted(r["factors"], r["relevance"])) for r in iso_rows],
                                        [r["large"] for r in iso_rows])
        return tmp

    # Model selection inside the calibration period only.
    inner_fit = [r for r in cal_studied if r["day"] <= inner_split]
    inner_check = [r for r in cal_studied if r["day"] > inner_split]
    expert = rec.expert_weights()
    ident = identifiable([r["factors"] for r in cal_studied])
    fitted_inner = fit_weights([r["factors"] for r in inner_fit], [r["abs_scar"] for r in inner_fit])
    blended_inner = blend_weights(expert, fitted_inner, ident)
    inner = {
        "expert": evaluate(make(expert, "expert", in_cal), inner_check)["spearman"],
        "fitted": evaluate(make(fitted_inner, "fitted", in_cal), inner_check)["spearman"],
        "blended": evaluate(make(blended_inner, "blended", in_cal), inner_check)["spearman"],
    }
    # Fitted weights are only usable where the data can identify them, so the candidates are expert vs blended.
    chosen = "blended" if inner["blended"] > inner["expert"] + 0.02 else "expert"

    fitted_full = fit_weights([r["factors"] for r in cal_studied], [r["abs_scar"] for r in cal_studied])
    models = {
        "expert": make(expert, "expert", in_cal, cal_studied),
        "fitted": make(fitted_full, "fitted", in_cal, cal_studied),
        "blended": make(blend_weights(expert, fitted_full, ident), "blended", in_cal, cal_studied),
    }
    final = models[chosen]

    test = [r for r in records if r["day"] >= test_start and r["abs_scar"] is not None]
    report = {
        "computed_at": datetime.now(UTC).isoformat(),
        "periods": {"calibration": [cal_start.isoformat(), cal_end.isoformat()], "inner_split": inner_split.isoformat(),
                    "test_from": test_start.isoformat()},
        "event_study": study_stats,
        "counts": {"events_scored": len(records), "calibration_events": len(in_cal),
                   "calibration_with_returns": len(cal_studied), "test_with_returns": len(test)},
        "h_table": table,
        "h_measured_on": {"methods": list(DETERMINISTIC_METHODS),
                          "n_by_type": {t: len(v) for t, v in sorted(by_type.items())}},
        "tail_coverage": tail_counts([r["factors"] for r in cal_studied]),
        "weights": {"expert": expert, "fitted": fitted_full, "final": final.weights},
        "identifiable_factors": ident,
        "model_selection_inner_check_spearman": inner,
        "chosen": chosen,
        "config_hash": final.config_hash,
        "test": {
            "final": evaluate(final, test),
            "expert": evaluate(models["expert"], test),
            "fitted": evaluate(models["fitted"], test),
            "blended": evaluate(models["blended"], test),
            "baselines": {
                "severity_only": _single_factor(test, "S_severity"),
                "sentiment_magnitude_only": _single_factor(test, "M_sentiment_magnitude"),
                "historical_reaction_only": _single_factor(test, "H_historical_reaction"),
            },
            "ablation_add_one_factor": _incremental(make, in_cal, cal_studied, test),
            "ablation_drop_one_factor": {
                f: evaluate(_drop(final, f), test)["spearman"] for f in FACTORS if final.weights[f] > 0
            },
        },
        "scope_note": "Validated only on firm-specific 8-K events with exact timestamps; macro, geopolitical "
                      "and social-only events have no single stock to test.",
    }
    return final, report, returns_


# Factors added one at a time, starting from event type alone (H: measured reaction per type).
INCREMENTAL_ORDER = ["H_historical_reaction", "S_severity", "M_sentiment_magnitude", "N_novelty",
                     "V_volume_corroboration", "E_entity_importance", "Q_source_credibility"]


def _incremental(make, corpus_rows, iso_rows, test) -> list[dict]:
    """Which factors add information? Expert weights restricted to the first n factors (renormalised), each
    model with its own percentile scale and isotonic P(large move) fitted on the calibration period only."""
    expert = rec.expert_weights()
    out = []
    for n in range(1, len(INCREMENTAL_ORDER) + 1):
        used = INCREMENTAL_ORDER[:n]
        total = sum(expert[f] for f in used)
        weights = {f: (expert[f] / total if f in used else 0.0) for f in FACTORS}
        m = make(weights, f"first {n}", corpus_rows, iso_rows)
        e = evaluate(m, test)
        out.append({"factors": used, "added": used[-1], "spearman": e["spearman"],
                    "spearman_ci95": e["spearman_ci95"], "auc": e["auc_large_move"], "pr_auc": e["pr_auc_large_move"],
                    "brier": (e["probability"] or {}).get("brier"), "ece": (e["probability"] or {}).get("ece"),
                    "precision_at_7": e["trigger_precision_impact_ge_7"], "n_at_7": e["n_triggered"]})
    return out


def _drop(model: ImpactModel, factor: str) -> ImpactModel:
    weights = {f: (0.0 if f == factor else w) for f, w in model.weights.items()}
    total = sum(weights.values()) or 1.0
    clone = ImpactModel(**{**model.__dict__, "weights": {f: w / total for f, w in weights.items()}})
    return clone


def save_outputs(root, model: ImpactModel, report: dict, returns_: list) -> None:
    model.save(root / "models" / "impact_model.json")
    out = root / "docs" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "impact_validation.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = ["raw_id,ticker,t0,car,scar,sigma,beta,n_est"]
    lines += [f"{r.event_key},{r.ticker},{r.t0},{r.car},{r.scar},{r.sigma},{r.beta},{r.n_est}" for r in returns_]
    (out / "event_study_8k.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
