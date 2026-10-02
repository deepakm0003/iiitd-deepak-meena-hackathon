"""Write the golden replay fixture (tests/golden/western_alliance.json) from the live store and current models.

Run on the machine that holds the database (the GPU server), then copy the fixture back:
    python scripts/make_golden.py
Regenerate deliberately when an assumption, model or the book changes, and review the diff: the fixture
records what the pipeline produced, so a changed number in review is a changed result, not a test detail.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from tripwire.factory import build_store
from tripwire.nlp.filing_lead import with_filing_leads
from tripwire.settings import get_settings
from tripwire.stress.service import StressService
from tripwire.stress.trigger import scenario_from_signal

ENTITY, EVENT_TYPE, FIRST_DAY = "WAL", "Credit Event", "2023-03-13"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    settings = get_settings()
    store = build_store(settings)
    signal = next(s for s in store.query_signals(entity=ENTITY, limit=1000)
                  if s["event_type"] == EVENT_TYPE and s["first_seen_at"].startswith(FIRST_DAY))
    ann = next(a for a in store.get_annotations() if a["primary"] == ENTITY and a["event_type"] == EVENT_TYPE
               and str(a["published_at"]).startswith(FIRST_DAY))
    doc = next(d for d in with_filing_leads(store, store.iter_documents()) if d.raw_id == ann["raw_id"])
    svc = StressService(store, settings.data_dir)
    result = svc.engine.run(scenario_from_signal(signal, svc.analogs, svc.shocks))
    fixture = {
        "generated_at": datetime.now(UTC).isoformat(),
        "provenance": "OBSERVED source document (SEC 8-K, public); outputs recorded from the pipeline as deployed",
        "document": json.loads(doc.model_dump_json()),
        "annotation": {k: ann[k] for k in ("primary", "event_type", "event_subtype", "event_method", "sentiment",
                                           "sentiment_label")} | {"factuality": ann["frame"]["factuality"]},
        "signal": {k: signal[k] for k in ("event_id", "first_seen_at", "headline", "primary_entity", "company",
                                          "event_type", "event_subtype", "event_method", "sentiment_score",
                                          "sentiment_label", "factuality", "frame", "impact_score",
                                          "impact_breakdown", "p_large_move", "corroboration")},
        "stress": {"k": result["scenario"]["k"], "pnl_total": result["pnl_total"],
                   "pnl_by_asset_class": result["pnl_by_asset_class"], "ecl_change": result["ecl_change"],
                   "capital": result["capital"], "n_positions_affected": result["n_positions_affected"]},
    }
    out = ROOT / "tests" / "golden" / "western_alliance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out}: impact {signal['impact_score']}, P&L {result['pnl_total']:,.0f}")


if __name__ == "__main__":
    main()
