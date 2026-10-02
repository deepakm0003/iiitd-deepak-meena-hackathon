"""Turn scored events into the Risk Engine's output: one machine-readable signal per event (contract v1.0).

Mandatory case-study fields: sentiment_score (-1..1), event_type (categorical), impact_score (1..10).
Everything else explains them: factor breakdown, evidence sentences, sources, model versions, config hash,
and a provenance tag per number (OBSERVED / MODEL / MEASURED / ASSUMPTION ...).
"""

from datetime import UTC, datetime

from tripwire.config import load_yaml
from tripwire.nlp.events import EventRules
from tripwire.scoring import records as rec
from tripwire.scoring.impact import ImpactModel, confidence

SCHEMA_VERSION = "1.0"
FACTOR_LABELS = {
    "S_severity": "event-type severity prior",
    "M_sentiment_magnitude": "strength of sentiment",
    "E_entity_importance": "company size",
    "N_novelty": "novelty (first report)",
    "V_volume_corroboration": "coverage volume",
    "Q_source_credibility": "source credibility",
    "H_historical_reaction": "historical market reaction to this event type",
}
FACTOR_PROVENANCE = {
    "S_severity": "ASSUMPTION:A-13", "M_sentiment_magnitude": "MODEL", "E_entity_importance": "DERIVED",
    "N_novelty": "MODEL", "V_volume_corroboration": "OBSERVED", "Q_source_credibility": "ASSUMPTION:A-14",
    "H_historical_reaction": "MEASURED",
}


def risk_level(impact: float, levels: dict[str, float]) -> tuple[str, str]:
    if impact >= levels["high"]:
        return "Critical", "Flash"
    if impact >= levels["medium"]:
        return "High", "Urgent"
    if impact >= levels["low"]:
        return "Medium", "Watch"
    return "Low", "Log"


def explanation(record: dict, scored: dict, conf: float) -> str:
    top = sorted(scored["contributions"].items(), key=lambda kv: -kv[1])[:3]
    drivers = ", ".join(f"{FACTOR_LABELS[f]} ({v:.2f})" for f, v in top if v > 0)
    who = "the economy / markets" if record["key"] == "MACRO" else record["key"]
    return (f"Impact {scored['impact']:.1f}/10 for {who} ({record['event_type']}): higher than "
            f"{scored['percentile']:.0f}% of calibration events. Main drivers: {drivers}. "
            f"{record['n_docs']} article(s) from {record['n_publishers']} publisher(s); sentiment "
            f"{record['sentiment']:+.2f}; confidence {conf:.2f}.")


def build_signals(store, model: ImpactModel, since: datetime | None = None) -> list[dict]:
    cfg = load_yaml("impact_weights.yaml")
    from tripwire.universe import load_universe

    universe = {c.ticker: c for c in load_universe()}
    period = tuple(datetime.fromisoformat(d).date() for d in model.calibration_period)
    importance = rec.entity_importance(store, list(universe), period)
    records = rec.build_records(store, importance, EventRules())
    annotations = {a["raw_id"]: a for a in store.get_annotations()}
    docs = {d.raw_id: d for d in store.iter_documents()}
    out = []
    for r in records:
        if since and r["first_seen"] < since:
            continue
        default_h = model.h_table.get("__default__", 0.5)
        r["factors"]["H_historical_reaction"] = model.h_table.get(r["event_type"], default_h)
        scored = model.score(r["factors"], r["relevance"])
        conf = confidence(r["event_confidence"], r["sentiment"], r["link_confidence"], r["corroboration"])
        level, tier = risk_level(scored["impact"], cfg["risk_levels"])
        members = [annotations[i] for i in r["doc_ids"] if i in annotations]
        rep = rec.representative(members) if members else {}
        evidence = [
            {**e, "doc_id": a["raw_id"]} for a in members[:5] for e in a.get("sentiment_evidence", [])[:1]
        ]
        sources = [
            {"source": docs[i].source, "title": docs[i].title, "url": docs[i].url,
             "published_at": docs[i].published_at.isoformat()}
            for i in r["doc_ids"][:10] if i in docs
        ]
        company = universe.get(r["key"])
        out.append({
            "schema_version": SCHEMA_VERSION,
            "event_id": r["event_id"],
            "first_seen_at": r["first_seen"].isoformat(),
            "headline": docs[rep["raw_id"]].title if rep and rep["raw_id"] in docs else (sources[0]["title"]
                                                                                          if sources else ""),
            "primary_entity": r["key"],
            "company": {"ticker": company.ticker, "name": company.sec_name, "cik": company.cik,
                        "sector": company.sector} if company else None,
            "affected_sectors": [company.sector] if company else ["Market-wide"],
            "event_type": r["event_type"],
            "event_subtype": r["event_subtype"],
            "event_method": r["event_method"],
            "event_type_probs": rep.get("event_probabilities", {}),
            "sentiment_score": r["sentiment"],
            "sentiment_label": "negative" if r["sentiment"] < -0.15 else "positive" if r["sentiment"] > 0.15
            else "neutral",
            "factuality": (rep.get("frame") or {}).get("factuality", "confirmed"),
            "frame": rep.get("frame", {}),
            "novelty_score": r["factors"]["N_novelty"],
            "corroboration": {"n_articles": r["n_docs"], "n_publishers": r["n_publishers"],
                              "sources": r["sources"], "score": r["corroboration"]},
            "impact_score": scored["impact"],
            "impact_breakdown": scored,
            "p_large_move": scored["p_large_move"],
            "confidence": conf,
            "risk_level": level,
            "severity_tier": tier,
            "explanation": explanation(r, scored, conf),
            "evidence": evidence[:3],
            "documents": sources,
            "model_versions": rep.get("model_versions", {}),
            "config_hash": model.config_hash,
            "provenance": {
                "sentiment_score": "MODEL", "event_type": "MODEL" if not r["event_method"].startswith("8k")
                else "OBSERVED", "impact_score": "MODEL (formula, MEASURED calibration)",
                "factors": FACTOR_PROVENANCE, "p_large_move": "MEASURED (isotonic, calibration period)",
            },
            "scored_at": datetime.now(UTC).isoformat(),
        })
    return out

