"""Scoring cycle: re-cluster events, score them with the frozen Impact model, store and export signals, then
launch Module B stress tests for signals that pass the portfolio-aware trigger."""

import json
from pathlib import Path

from tripwire.nlp.cluster_run import cluster_all
from tripwire.scoring.impact import ImpactModel
from tripwire.scoring.signals import build_signals


def score_cycle(store, model: ImpactModel, export_path: Path | None = None, stress=None) -> dict:
    cluster_stats = cluster_all(store)
    payloads = build_signals(store, model)
    changed = store.upsert_signals(payloads, prune=True)
    if export_path:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = export_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            for p in sorted(payloads, key=lambda p: p["first_seen_at"]):
                fh.write(json.dumps(p, default=str) + "\n")
        tmp.replace(export_path)
    runs = stress.auto(payloads) if stress else []
    return {**cluster_stats, "signals": len(payloads), "signals_changed": changed,
            "impact_ge_7": sum(p["impact_score"] >= 7 for p in payloads), "stress_runs": len(runs)}
