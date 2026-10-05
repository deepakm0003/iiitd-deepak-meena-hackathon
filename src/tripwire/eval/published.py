"""The validation numbers the website and dashboard show, read from the evaluation outputs in docs/results.

Nothing here computes or rounds a new number: every value comes from a result file written by an evaluation
command (eval-gold, calibrate, the tier and agreement scripts), so the site always shows what was last measured.
A missing file gives None for that section instead of a made-up value.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

FILES = {
    "locked_after": "gold_eval.json",
    "locked_before": "gold_eval_baseline.json",
    "fresh": "gold_eval_fresh.json",
    "fresh_tiers": "fresh_tier_precision.json",
    "fresh2": "gold_eval_fresh2.json",
    "fresh2_tiers": "fresh2_tier_precision.json",
    "impact": "impact_validation.json",
    "agreement": "silver_agreement.json",
}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _event(report: dict | None) -> dict | None:
    if not report or not report.get("on_sample_test"):
        return None
    test = report["on_sample_test"]
    return {
        "n": test["n"],
        "accuracy": test["accuracy"],
        "macro_f1": test["macro_f1"],
        "weighted_f1": test.get("weighted_f1"),
        "entity_accuracy": report.get("entity_accuracy_test"),
        "per_class": {c: {"precision": v["precision"], "recall": v["recall"], "support": v["support"]}
                      for c, v in test.get("per_class", {}).items()},
    }


def published_metrics(root: Path) -> dict:
    results = root / "docs" / "results"
    data = {k: _load(results / name) for k, name in FILES.items()}
    impact = (data["impact"] or {}).get("test", {}).get("final")
    agreement = data["agreement"] or {}
    gold_dir = root / "data" / "gold"
    label_files = [gold_dir / "human_check.jsonl", *sorted(gold_dir.glob("fresh*_labels.jsonl"))]
    labels = sum(len(f.read_text(encoding="utf-8").splitlines()) for f in label_files if f.exists())
    register = root / "config" / "assumptions_register.yaml"
    assumptions = (len(set(re.findall(r"\bA-\d+\b", register.read_text(encoding="utf-8"))))
                   if register.exists() else None)
    taxonomy = root / "config" / "taxonomy.yaml"
    classes = len(re.findall(r"^  - name:", taxonomy.read_text(encoding="utf-8"), re.M)) if taxonomy.exists() else None
    return {
        "human_labels": labels,
        "event_classes": classes,
        "assumptions": assumptions,
        "locked_test": {"before": _event(data["locked_before"]), "after": _event(data["locked_after"])},
        # the latest fresh out-of-time test is the headline; the earlier one is kept for comparison
        "fresh_test": ({**_event(data["fresh2"]), "tiers": data["fresh2_tiers"], "set": "fresh2"} if data["fresh2"]
                       else {**(_event(data["fresh"]) or {}), "tiers": data["fresh_tiers"], "set": "fresh"}
                       if data["fresh"] else None),
        "fresh_test_previous": ({**_event(data["fresh"]), "tiers": data["fresh_tiers"]}
                                if data["fresh2"] and data["fresh"] else None),
        "impact": None if not impact else {
            "n": impact["n"], "auc": impact["auc_large_move"], "spearman": impact["spearman"],
            "brier": impact["probability"]["brier"], "brier_base_rate": impact["probability"]["brier_base_rate"],
            "pr_auc": impact["pr_auc_large_move"], "base_rate": impact["base_rate_large_move"],
            "computed_at": (data["impact"] or {}).get("computed_at"),
        },
        "agreement": {"event_kappa": agreement.get("event_type", {}).get("cohen_kappa"),
                      "entity_kappa": agreement.get("entity", {}).get("cohen_kappa"),
                      "n": agreement.get("n")} if agreement else None,
        "sources": {k: {"file": f"docs/results/{name}",
                        "updated_at": datetime.fromtimestamp((results / name).stat().st_mtime, UTC).isoformat()}
                    for k, name in FILES.items() if (results / name).exists()},
    }
