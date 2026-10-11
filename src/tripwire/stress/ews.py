"""Early-warning watchlist: every name in the book rated Green / Amber / Red, with the evidence behind it.

Large-corporate names (Tranche 2): recent signals about the issuer, the 3 strongest combined by noisy-OR,
    score = 1 - prod_j (1 - w_j),   w_j = P(large move)_j x adverse_j x factuality_j x 0.5 ** (age_j / half-life)
  Only the strongest items count: a mega-cap with dozens of routine stories is not riskier for being covered.
  P(large move) is MEASURED (isotonic fit on the event study); the other weights are A-28.
SME obligors (Tranche 1): the behavioural model's calibrated distress probability (MODEL, out-of-time AUC
  in docs/results/merchant_risk_validation.json), combined the same way with disasters named in the
  obligor's home state, if the disaster shows scale (3+ publishers or Impact >= 7).
Hard flags (8-K 1.03 bankruptcy, 2.04 acceleration, 4.02 non-reliance) make a name Red regardless of score.
"""

from datetime import UTC, datetime

from tripwire.config import load_yaml
from tripwire.stress.engine import severity_k
from tripwire.stress.geo import states_from
from tripwire.stress.trigger import hard_flags, position_exposure

GEO_CLASSES = {"Natural Disaster/Supply Chain"}


def _age_days(signal: dict, now: datetime) -> float:
    return max(0.0, (now - datetime.fromisoformat(signal["first_seen_at"])).total_seconds() / 86400)


def _status(score: float, flags: list[str], th: dict, cfg: dict) -> str:
    if any(f in cfg["hard_flags_red"] for f in flags) or score >= th["red"]:
        return "Red"
    if any(f in cfg["hard_flags_amber"] for f in flags) or score >= th["amber"]:
        return "Amber"
    return "Green"


def _large(signal: dict, cfg: dict) -> bool:
    """A disaster counts for a whole state only with evidence of scale: wide coverage or a high Impact."""
    publishers = (signal.get("corroboration") or {}).get("n_publishers", 1)
    return publishers >= cfg.get("geo_min_publishers", 3) or signal["impact_score"] >= cfg.get("geo_min_impact", 7.0)


def _noisy_or(weights: list[float], base: float = 0.0) -> float:
    survive = 1.0 - base
    for w in weights:
        survive *= 1.0 - min(1.0, max(0.0, w))
    return 1.0 - survive


def signal_weight(signal: dict, now: datetime, cfg: dict) -> tuple[float, dict]:
    p = signal.get("p_large_move")
    p = p if p is not None else signal["impact_score"] / 10
    adverse = cfg["adverse_weight"][signal.get("sentiment_label", "neutral")]
    fact = cfg["factuality_weight"].get(signal.get("factuality", "confirmed"), 0.5)
    credibility = (signal.get("impact_breakdown") or {}).get("factors", {}).get("Q_source_credibility", 1.0)
    age = _age_days(signal, now)
    decay = 0.5 ** (age / cfg["half_life_days"])
    w = p * adverse * fact * credibility * decay
    return w, {"event_id": signal["event_id"], "headline": signal.get("headline", "")[:140],
               "event_type": signal["event_type"], "impact": signal["impact_score"], "p_large_move": round(p, 4),
               "adverse": adverse, "factuality": fact, "credibility": round(credibility, 3),
               "age_days": round(age, 1), "decay": round(decay, 3),
               "weight": round(w, 4)}


def watchlist(book: dict, signals: list[dict], now: datetime | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or load_yaml("book.yaml")["early_warning"]
    now = now or datetime.now(UTC)
    recent = [s for s in signals if _age_days(s, now) <= cfg["lookback_days"]]
    by_entity: dict[str, list[dict]] = {}
    for s in recent:
        by_entity.setdefault(s["primary_entity"], []).append(s)
    geo_events = [(s, states_from((s.get("frame") or {}).get("places", []))) for s in recent
                  if s["event_type"] in GEO_CLASSES and s.get("sentiment_label") != "positive" and _large(s, cfg)]

    rows = []
    issuers: dict[str, list[dict]] = {}
    for pos in book["tranche2"]:
        if pos.get("issuer"):
            issuers.setdefault(pos["issuer"], []).append(pos)
    for issuer, positions in issuers.items():
        drivers, flags = [], []
        for s in by_entity.get(issuer, []):
            w, why = signal_weight(s, now, cfg)
            flags += hard_flags(s)
            if w > 0 or hard_flags(s):
                drivers.append(why)
        top = sorted((d["weight"] for d in drivers), reverse=True)[: cfg.get("top_evidence", 3)]
        score = _noisy_or(top)  # strongest items only: dozens of routine stories about a mega-cap are not risk
        rows.append({
            "name": issuer, "tranche": 2, "positions": [p["id"] for p in positions],
            "sector": positions[0].get("sector"), "exposure": round(sum(position_exposure(p) for p in positions), 2),
            "score": round(score, 4), "status": _status(score, flags, cfg["thresholds"]["issuer"], cfg),
            "hard_flags": sorted(set(flags)), "drivers": sorted(drivers, key=lambda d: -d["weight"])[:5],
            "provenance": "MEASURED P(large move) x ASSUMPTION A-28 weights",
        })
    for pos in book["tranche1"]:
        if "risk_score" in pos:
            base = pos["risk_score"]
            drivers = [{"source": "behavioural model", "weight": round(base, 4),
                        "detail": f"calibrated probability of a card-volume collapse next year (grade {pos['grade']}); "
                                  "a proxy event from card transactions, not a probability of default"}]
        else:  # an uploaded SME loan has no card history: its grade's PD is the base risk (A-05)
            base = pos["pd"]
            drivers = [{"source": "grade PD", "weight": round(base, 4),
                        "detail": f"one-year probability of default of grade {pos['grade']} (uploaded position)"}]
        for s, states in geo_events:
            if pos.get("state") in states:
                age = _age_days(s, now)
                w = cfg["geography_weight"] * severity_k(s["impact_score"]) * 0.5 ** (age / cfg["half_life_days"])
                drivers.append({"source": "event in home state", "event_id": s["event_id"],
                                "headline": s.get("headline", "")[:140], "state": pos["state"],
                                "age_days": round(age, 1), "weight": round(w, 4)})
        score = _noisy_or([d["weight"] for d in drivers[1:]], base=base)
        rows.append({
            "name": pos["name"], "tranche": 1, "positions": [pos["id"]], "sector": pos.get("sector"),
            "state": pos.get("state"), "grade": pos["grade"], "exposure": round(position_exposure(pos), 2),
            "score": round(score, 4), "status": _status(score, [], cfg["thresholds"]["sme"], cfg), "hard_flags": [],
            "drivers": drivers, "provenance": "MODEL (behavioural, proxy target) + ASSUMPTION A-28",
        })
    order = {"Red": 0, "Amber": 1, "Green": 2}
    rows.sort(key=lambda r: (order[r["status"]], -r["score"] * r["exposure"]))
    counts = {k: sum(r["status"] == k for r in rows) for k in order}
    at_risk = {k: round(sum(r["exposure"] for r in rows if r["status"] == k), 2) for k in order}
    return {"as_of": now.isoformat(), "lookback_days": cfg["lookback_days"], "counts": counts,
            "exposure_by_status": at_risk, "names": rows}
