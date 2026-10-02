"""Assemble one factor record per event from the store (annotations + clusters + prices + event study).

Leakage controls:
  - Entity importance E uses dollar volume measured only inside the calibration window, so no test-period
    market data enters any factor.
  - Factor H is filled in later from a table fitted on calibration events only (see calibrate.py).
"""

from datetime import date, datetime

from tripwire.config import load_yaml
from tripwire.scoring.impact import volume_factor

MACRO_IMPORTANCE = 0.7  # assumption A-19: economy-wide events matter to every large book


def representative(annotations: list[dict]) -> dict:
    """The document that decides the event's type: deterministic evidence (8-K item, rule) first, then the
    most confident classifier output, then the earliest."""
    def rank(a):
        method = a["event_method"]
        deterministic = method.startswith("8k_item") or method.startswith("rule")
        return (not deterministic, -a["event_confidence"], a["published_at"])
    return min(annotations, key=rank)


def entity_importance(store, tickers: list[str], window: tuple[date, date]) -> dict[str, float]:
    """Percentile rank of median daily dollar volume (close x volume) within the window, among universe names."""
    medians = {}
    for ticker in tickers:
        values = sorted((b.close or b.adj_close) * (b.volume or 0) for b in store.get_prices(ticker)
                        if window[0] <= b.date <= window[1] and b.volume)
        if values:
            medians[ticker] = values[len(values) // 2]
    ranked = sorted(medians, key=medians.get)
    n = len(ranked)
    return {t: round((i + 1) / n, 4) for i, t in enumerate(ranked)} if n else {}


def build_records(store, importance: dict[str, float], severity) -> list[dict]:
    annotations = {a["raw_id"]: a for a in store.get_annotations()}
    records = []
    for event in store.get_events():
        members = [annotations[i] for i in event["detail"]["doc_ids"] if i in annotations]
        if not members or event["key"] == "NONE":
            continue
        rep = representative(members)
        key = event["key"]
        if key == "MACRO":
            # Relevance of a market-wide event = strength of its market-wide evidence (regulator 1.0 ... themes 0.6)
            relevance = max((a.get("macro_evidence", 0.0) for a in members), default=0.0)
            link_conf, e_factor = 1.0, MACRO_IMPORTANCE
        else:
            ents = [e for a in members for e in a["entities"] if e["ticker"] == key]
            relevance = max((e["relevance"] for e in ents), default=0.0)
            link_conf = max((e["link_confidence"] for e in ents), default=0.0)
            e_factor = importance.get(key, 0.5)
        sentiments = [a["sentiment"] for a in members]
        sentiment = sum(sentiments) / len(sentiments)
        records.append({
            "event_id": event["event_id"],
            "key": key,
            "first_seen": event["first_seen"],
            "event_type": rep["event_type"],
            "event_subtype": rep.get("event_subtype"),
            "event_method": rep["event_method"],
            "event_confidence": rep["event_confidence"],
            "sentiment": round(sentiment, 4),
            "relevance": relevance,
            "link_confidence": link_conf,
            "corroboration": event["corroboration"],
            "n_docs": event["n_docs"],
            "n_publishers": event["n_publishers"],
            "sources": event["detail"]["sources"],
            "doc_ids": event["detail"]["doc_ids"],
            "factors": {
                "S_severity": severity.prior(rep["event_type"], rep.get("event_subtype")),
                "M_sentiment_magnitude": min(1.0, abs(sentiment)),
                "E_entity_importance": e_factor,
                "N_novelty": event["novelty"],
                "V_volume_corroboration": round(volume_factor(event["n_docs"], event["n_publishers"]), 4),
                "Q_source_credibility": event["credibility"],
                "H_historical_reaction": None,  # filled from the calibration-only H table
            },
        })
    return records


def filing_events(store) -> list[tuple[str, str, datetime]]:
    """(raw_id, ticker, acceptance time) for every 8-K: the inputs of the event study."""
    return [
        (str(doc.raw_id), doc.hints["ticker"], doc.published_at)
        for doc in store.iter_documents() if doc.source == "edgar" and doc.hints.get("ticker")
    ]


def expert_weights() -> dict[str, float]:
    return dict(load_yaml("impact_weights.yaml")["weights"])
