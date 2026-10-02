"""Portfolio-aware stress trigger: which signals launch a stress test, and the scenario each one implies.

A signal launches a stress test when all of these hold (every check is reported, pass or fail):
  1. its event class has a shock definition (config/shocks.yaml): the stress engine can translate it;
  2. it is a fact, not talk: factuality confirmed or announced (rumours, opinions and denials are watched by
     the early-warning list instead);
  3. it is adverse: by nature (a deterministic subtype such as bankruptcy, bank run, downgrade, sanctions,
     disaster; set only by 8-K items and high-precision rules), by sentiment (not positive), or through an
     8-K hard flag (bankruptcy 1.03, acceleration 2.04, non-reliance 4.02). Nature beats tone: a bank's own
     statement during a run reads as reassuring (Western Alliance, March 2023: sentiment +0.86);
  4. Impact >= T(exposure): the bar is lower the more of the book the event touches through the channels
     its class actually has (a macro shock has no geography layer, so naming a state does not count) (A-27):
       direct exposure >= 2% of the book   -> 5.5
       any direct exposure                 -> 6.0
       indirect (sector / geography) >= 10% -> 6.5
       otherwise (market-wide channel only) -> 7.0
     A hard flag on a name the book lends to triggers regardless of Impact.
"""

from datetime import UTC, datetime, timedelta

from tripwire.config import load_yaml
from tripwire.stress.engine import Scenario, build_layers, severity_k
from tripwire.stress.geo import states_from

HARD_FLAG_ITEMS = {"1.03": "bankruptcy", "2.04": "acceleration of a financial obligation",
                   "4.02": "non-reliance on previously issued financial statements"}
TRIGGER_FACTUALITY = {"confirmed", "announced"}
ADVERSE_SUBTYPES = {"bankruptcy", "default_or_covenant_breach", "accelerated_obligation", "liquidity_stress",
                    "rating_downgrade", "sanctions", "trade_restriction", "armed_conflict", "disaster",
                    "supply_disruption", "cybersecurity_incident", "operational_disruption", "delisting_notice",
                    "non_reliance_on_financials", "litigation_or_enforcement"}


def position_exposure(pos: dict) -> float:
    if pos["type"] == "swap":
        return float(pos["notional"]) * pos.get("risk_weight", 0.02)  # notional is not money at risk
    return float(pos.get("ead") or abs(pos.get("market_value", 0.0)))


def hard_flags(signal: dict) -> list[str]:
    method = signal.get("event_method", "")
    flags = []
    if method.startswith("8k_item:") and (item := method.split(":", 1)[1]) in HARD_FLAG_ITEMS:
        flags.append(item)
    if signal.get("event_subtype") == "bankruptcy" and "1.03" not in flags:
        flags.append("bankruptcy")
    return flags


def exposure(book: dict, signal: dict, states: set[str], sector_scope: str, layers: list[str] | None = None) -> dict:
    """Share of the book reached by each channel the event's class has (all channels if layers is None)."""
    positions = book["tranche1"] + book["tranche2"]
    total = sum(position_exposure(p) for p in positions) or 1.0
    layers = ["entity", "sector", "geography"] if layers is None else layers
    entity = signal.get("primary_entity") if "entity" in layers else None
    sector = (signal.get("company") or {}).get("sector") if "sector" in layers else None
    states = states if "geography" in layers else set()
    direct = sum(position_exposure(p) for p in positions if entity and p.get("issuer") == entity)
    in_sector = sum(position_exposure(p) for p in positions if sector and p.get("sector") == sector
                    and p.get("issuer") != entity and (p["type"] != "sme_loan" or sector_scope == "all"))
    in_states = sum(position_exposure(p) for p in positions if p.get("state") in states)
    return {"direct": round(direct / total, 5), "sector": round(in_sector / total, 5),
            "geography": round(in_states / total, 5), "book_exposure": round(total, 2)}


def threshold(exp: dict, cfg: dict) -> tuple[float, str]:
    if exp["direct"] >= cfg["direct_large_share"]:
        return cfg["direct_large"], f"direct exposure {exp['direct']:.1%} of the book"
    if exp["direct"] > 0:
        return cfg["direct_any"], f"direct exposure {exp['direct']:.2%} of the book"
    indirect = max(exp["sector"], exp["geography"])
    if indirect >= cfg["indirect_share"]:
        return cfg["indirect"], f"indirect exposure {indirect:.1%} (sector or geography)"
    return cfg["market_only"], "market-wide channel only"


def decide(signal: dict, book: dict, shocks_cfg: dict | None = None, cfg: dict | None = None,
           now: datetime | None = None, max_age_days: float | None = None) -> dict:
    """Whether this signal launches a stress test, with every check spelled out for the dashboard."""
    shocks_cfg = shocks_cfg or load_yaml("shocks.yaml")
    cfg = cfg or load_yaml("book.yaml")["stress_trigger"]
    spec = shocks_cfg["classes"].get(signal["event_type"])
    states = states_from((signal.get("frame") or {}).get("places", []))
    flags = hard_flags(signal)
    exp = exposure(book, signal, states, (spec or {}).get("sector_scope", "corporate"), (spec or {}).get("layers", []))
    bar, why = threshold(exp, cfg)
    impact = signal["impact_score"]
    checks = {
        "stress_mappable": {"ok": spec is not None, "detail": signal["event_type"]},
        "factual": {"ok": signal.get("factuality", "confirmed") in TRIGGER_FACTUALITY or bool(flags),
                    "detail": signal.get("factuality", "confirmed")},
        "adverse": {"ok": signal.get("sentiment_label") != "positive" or bool(flags)
                    or signal.get("event_subtype") in ADVERSE_SUBTYPES,
                    "detail": f"sentiment {signal.get('sentiment_score', 0):+.2f}"
                              + (f"; adverse by nature ({signal['event_subtype']})"
                                 if signal.get("event_subtype") in ADVERSE_SUBTYPES else "")
                              + (f"; hard flags {flags}" if flags else "")},
        "severe_enough": {"ok": impact >= bar or (bool(flags) and exp["direct"] > 0),
                          "detail": f"Impact {impact:.1f} vs threshold {bar} ({why})"
                                    + ("; hard flag on a name the book lends to" if flags and exp["direct"] else "")},
    }
    if max_age_days is not None:
        seen = datetime.fromisoformat(signal["first_seen_at"])
        fresh = (now or datetime.now(UTC)) - seen <= timedelta(days=max_age_days)
        checks["recent"] = {"ok": fresh, "detail": f"first seen {seen.date()}"}
    return {"event_id": signal["event_id"], "trigger": all(c["ok"] for c in checks.values()), "threshold": bar,
            "exposure": exp, "states": sorted(states), "hard_flags": flags, "checks": checks}


def scenario_from_signal(signal: dict, analogs: dict, shocks_cfg: dict | None = None,
                         hard: list[str] | None = None) -> Scenario:
    shocks_cfg = shocks_cfg or load_yaml("shocks.yaml")
    event_type = signal["event_type"]
    company = signal.get("company") or {}
    sector = company.get("sector")
    spec = shocks_cfg["classes"].get(event_type, {})
    return Scenario(
        name=f"{event_type}: {signal.get('headline', '')[:90]}",
        event_type=event_type,
        subtype=signal.get("event_subtype"),
        entity=company.get("ticker"),
        sector=sector,
        states=states_from((signal.get("frame") or {}).get("places", [])),
        impact=signal["impact_score"],
        k=severity_k(signal["impact_score"]),
        layers=build_layers(event_type, sector, analogs, shocks_cfg, company.get("ticker")),
        event_id=signal["event_id"],
        hard_flags=hard_flags(signal) if hard is None else hard,
        sector_scope=spec.get("sector_scope", "corporate"),
    )


def custom_scenario(event_type: str, impact: float, analogs: dict, entity: str | None = None,
                    sector: str | None = None, states: list[str] | None = None, hard: list[str] | None = None,
                    shocks_cfg: dict | None = None) -> Scenario:
    """A what-if scenario from the dashboard: the same layers as a live event of that class."""
    shocks_cfg = shocks_cfg or load_yaml("shocks.yaml")
    if event_type not in shocks_cfg["classes"]:
        raise ValueError(f"no shock definition for {event_type!r}; choose from {sorted(shocks_cfg['classes'])}")
    spec = shocks_cfg["classes"][event_type]
    return Scenario(
        name=f"What-if: {event_type}" + (f" at {entity}" if entity else "") + (f" in {', '.join(states)}"
                                                                                if states else ""),
        event_type=event_type, subtype=None, entity=entity, sector=sector, states=set(states or []),
        impact=impact, k=severity_k(impact), layers=build_layers(event_type, sector, analogs, shocks_cfg, entity),
        hard_flags=list(hard or []), sector_scope=spec.get("sector_scope", "corporate"),
    )
