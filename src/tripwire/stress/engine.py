"""Event-driven stress test of the wholesale book, with a causal path for every position.

    dV_p = sum over channels c of  sensitivity_p,c x shock_c(event) x k(Impact)

Channels (most specific layer wins, so nothing is counted twice):
  direct     the position's issuer/borrower IS the event's company        -> entity layer
  sector     same sector as the event's company                           -> sector layer
  geography  obligor's home state is a place named by the event           -> geography layer
  market     systemic risk factors (rates, spreads, equity, volatility)   -> systemic layer
Valuation: equities by beta x move; bonds by -duration x (rate + spread) plus convexity; swaps by DV01;
index puts by Black-Scholes repricing; loans by IFRS 9 expected credit loss with stage migration.
Capital: CET1 after tax over risk-weighted assets after migration, against a Basel or RBI floor; reverse stress
finds the severity at which CET1 hits the floor.
Invariant (tested): total P&L == sum of every path contribution; positions with no channel have dV == 0.
"""

import math
from dataclasses import dataclass, field

from tripwire.config import load_yaml
from tripwire.portfolio.pricing import bs_put, lifetime_pd

HY_GRADES = {"BB", "B", "CCC"}


def source_type(source: str) -> str:
    """HISTORICAL (measured analog), ASSUMPTION (registered A-xx), HARD_FLAG (8-K item) or PRICING (model)."""
    if source.startswith("MEASURED"):
        return "HISTORICAL"
    if source.startswith("assumption"):
        return "ASSUMPTION"
    return "HARD_FLAG" if source == "hard flag" else "PRICING"


def _exposure(pos: dict) -> float:
    if pos["type"] == "swap":
        return float(pos["notional"])
    return float(pos.get("ead") or abs(pos.get("market_value", 0.0)))
STAGE2_PD_MULTIPLE, STAGE2_PD_ABSOLUTE = 3.0, 0.20  # A-09: ECB-style SICR backstops


@dataclass
class Scenario:
    name: str
    event_type: str
    subtype: str | None
    entity: str | None          # ticker of the event's company, if any
    sector: str | None          # that company's sector
    states: set[str]            # US states named by the event
    impact: float
    k: float                    # severity scale applied to the severe-end shocks
    layers: dict[str, dict]     # layer -> {factor: {"value": x, "source": "..."}}
    event_id: str | None = None
    hard_flags: list[str] = field(default_factory=list)  # e.g. 8-K 1.03 bankruptcy -> stage 3
    sector_scope: str = "corporate"  # A-25: "all" lets the sector layer reach SME obligors too

    def shock(self, layer: str, factor: str) -> tuple[float, str] | None:
        """Severity-scaled shock. Moves scale linearly (k x move); PD multipliers as 1 + k x (m - 1), so that
        k = 0 means 'no change' for both."""
        spec = self.layers.get(layer, {}).get(factor)
        if not spec:
            return None
        value = 1 + self.k * (spec["value"] - 1) if factor == "pd_mult" else spec["value"] * self.k
        return value, spec["source"]


def severity_k(impact: float) -> float:
    """Impact 7 -> 40% of the severe shock, Impact 10 -> 100% (A-15); below 7 scales down to 10%."""
    return round(min(1.0, max(0.1, 0.4 + 0.6 * (impact - 7) / 3)), 4)


def systemic_applies(spec: dict, entity: str | None, sector: str | None) -> bool:
    """Whether the market-wide layer applies to this event (A-25, config/shocks.yaml systemic_when)."""
    when = spec.get("systemic_when", "always")
    if when == "financials":
        return sector == "Financials"
    if when == "market_wide":
        return entity is None
    return True


def build_layers(event_type: str, sector: str | None, analogs: dict, shocks_cfg: dict | None = None,
                 entity: str | None = None) -> dict:
    shocks_cfg = shocks_cfg or load_yaml("shocks.yaml")
    spec = shocks_cfg["classes"].get(event_type)
    if not spec:
        return {}
    layers: dict[str, dict] = {}
    analog = analogs.get(event_type)
    for layer in spec["layers"]:
        if layer == "systemic" and not systemic_applies(spec, entity, sector):
            continue
        values = spec.get(layer, {})
        src = f"assumption A-15 (config/shocks.yaml {event_type}.{layer})"
        out = {}
        if layer == "systemic":
            if analog:
                msrc = f"MEASURED analog: {analog['name']} ({analog['start']} to {analog['end']})"
                for f in ("equity_market", "rate_10y_bp", "ig_spread_bp", "hy_spread_bp", "vol_pts"):
                    out[f] = {"value": analog[f], "source": msrc}
            else:
                mapping = {"equity": "equity_market", "rate_10y_bp": "rate_10y_bp", "ig_spread_bp": "ig_spread_bp",
                           "vol_pts": "vol_pts"}
                for k_cfg, f in mapping.items():
                    if k_cfg in values:
                        out[f] = {"value": values[k_cfg], "source": src}
                if "ig_spread_bp" in out:
                    out["hy_spread_bp"] = {"value": 2.5 * out["ig_spread_bp"]["value"], "source": src + " x2.5 for HY"}
            if "pd_mult" in values:
                out["pd_mult"] = {"value": values["pd_mult"], "source": src}
        else:
            for f, v in values.items():
                out[f if f != "equity" else "equity"] = {"value": v, "source": src}
            if layer == "sector" and analog and sector and analog.get("sector_etf") == "KRE" and sector == "Financials":
                out["equity"] = {"value": analog["equity_sector"],
                                 "source": f"MEASURED analog: {analog['name']} (KRE regional banks)"}
        layers[layer] = out
    return layers


# --------------------------------------------------------------------------------------------- engine
class StressEngine:
    def __init__(self, book: dict, market_inputs: dict, cfg: dict | None = None) -> None:
        cfg = cfg or load_yaml("book.yaml")
        self.book = book
        self.betas = market_inputs.get("betas", {})
        self.grades = cfg["grades"]
        self.capital = book["capital"]
        self.equity_rw = cfg["capital"]["equity_risk_weight"]

    # ---- channels -------------------------------------------------------------------------------
    def _channel(self, pos: dict, sc: Scenario) -> tuple[str, str] | None:
        issuer = pos.get("issuer")
        if sc.entity and issuer == sc.entity and "entity" in sc.layers:
            return "direct", f"{pos['id']}: issuer/borrower is the event's company {sc.entity}"
        if (sc.sector and pos.get("sector") == sc.sector and "sector" in sc.layers
                and (pos["type"] != "sme_loan" or sc.sector_scope == "all")):
            return "sector", f"{pos['id']}: same sector as {sc.entity or 'the event'} ({sc.sector})"
        if pos.get("state") and pos["state"] in sc.states and "geography" in sc.layers:
            return "geography", f"{pos['id']}: home state {pos['state']} is named by the event"
        return None

    @staticmethod
    def _why_not(pos: dict, sc: Scenario) -> str:
        """Why a position has no path: shown so that a zero is explained, not just absent."""
        if sc.k == 0:
            return "severity k = 0: no shock applied"
        if sc.sector and pos.get("sector") == sc.sector and pos["type"] == "sme_loan" and "sector" in sc.layers:
            return (f"same sector ({sc.sector}) but this event's sector shock reaches large-corporate peers only; "
                    "SMEs are reached through their home state (A-25)")
        if "systemic" in sc.layers:
            return "not linked to the event's company, sector or places; no market-wide factor moves this position"
        return ("not the event's company, not in its sector, not in a named state, and the event has no "
                "market-wide layer")

    # ---- valuation ------------------------------------------------------------------------------
    def _paths(self, pos: dict, sc: Scenario) -> tuple[list[dict], dict]:
        """Contributions for one position, and its post-stress state (pd, stage, grade, value)."""
        channel = self._channel(pos, sc)
        layer = {"direct": "entity", "sector": "sector", "geography": "geography"}.get(channel[0]) if channel else None
        systemic = "systemic" in sc.layers
        paths: list[dict] = []
        after: dict = {}

        def add(ch, reason, factor, shock, unit, source, sensitivity, dv):
            paths.append({"channel": ch, "reason": reason, "factor": factor, "shock": round(shock, 6),
                          "unit": unit, "source": source, "source_type": source_type(source),
                          "sensitivity": round(sensitivity, 6), "dv": round(dv, 2)})

        kind = pos["type"]
        if kind == "equity":
            mv, beta = pos["market_value"], self.betas.get(pos["issuer"], {})
            if channel and layer and (s := sc.shock(layer, "equity")):
                sens = mv * (beta.get("beta_sector", 1.0) if layer == "sector" else 1.0)
                add(channel[0], channel[1], f"{layer} equity move", s[0], "return", s[1], sens, sens * s[0])
            elif systemic and (s := sc.shock("systemic", "equity_market")):
                sens = mv * beta.get("beta_market", 1.0)
                add("market", f"{pos['id']}: market beta {beta.get('beta_market', 1.0):.2f}", "equity market",
                    s[0], "return", s[1], sens, sens * s[0])
        elif kind == "bond":
            mv, dur, conv = pos["market_value"], pos["duration"], pos["convexity"]
            dr = dsp = 0.0
            if systemic and (s := sc.shock("systemic", "rate_10y_bp")):
                dr = s[0] / 1e4
                add("market", f"{pos['id']}: duration {dur:.2f} to the 10y rate", "10y rate", s[0], "bp", s[1],
                    -mv * dur / 1e4, -mv * dur * dr)
            spread = None
            if channel and layer and (s := sc.shock(layer, "spread_bp")):
                spread = (channel[0], channel[1], f"{layer} credit spread", s)
            elif systemic:
                f = "hy_spread_bp" if pos["grade"] in HY_GRADES else "ig_spread_bp"
                if s := sc.shock("systemic", f):
                    spread = ("market", f"{pos['id']}: {'HY' if f.startswith('hy') else 'IG'} spread, grade "
                              f"{pos['grade']}", f.replace("_bp", "").replace("_", " "), s)
            if spread:
                ch, reason, factor, s = spread
                dsp = s[0] / 1e4
                add(ch, reason, factor, s[0], "bp", s[1], -mv * dur / 1e4, -mv * dur * dsp)
            if dr or dsp:
                ch = spread[0] if spread else "market"
                add(ch, f"{pos['id']}: convexity {conv:.1f} (second-order price effect)", "convexity",
                    (dr + dsp) * 1e4, "bp", "pricing", 0.5 * mv * conv / 1e8, 0.5 * mv * conv * (dr + dsp) ** 2)
        elif kind == "swap":
            if systemic and (s := sc.shock("systemic", "rate_10y_bp")):
                add("market", f"{pos['id']}: DV01 {pos['dv01']:+,.0f} per bp", "10y rate", s[0], "bp", s[1],
                    pos["dv01"], pos["dv01"] * s[0])
        elif kind == "index_put":
            eq, vol = sc.shock("systemic", "equity_market"), sc.shock("systemic", "vol_pts")
            if systemic and (eq or vol):
                spot = pos["spot"] * (1 + (eq[0] if eq else 0.0))
                new_vol = pos["vol"] + (vol[0] / 100 if vol else 0.0)
                new_value = bs_put(spot, pos["strike"], pos["expiry_years"], new_vol) * pos["units"]
                dv = new_value - pos["market_value"]
                add("market", f"{pos['id']}: hedge reprices (spot {eq[0] if eq else 0:+.2%}, vol "
                    f"{(vol[0] if vol else 0):+.1f} pts)", "equity market and volatility",
                    eq[0] if eq else 0.0, "return", (eq or vol)[1], dv / (eq[0] if eq and eq[0] else 1.0), dv)
        elif kind in ("sme_loan", "corporate_loan"):
            mult, source, ch_name, reason = 1.0, None, None, None
            if channel and layer and (s := sc.shock(layer, "pd_mult")):
                mult, source, ch_name, reason = s[0], s[1], channel[0], channel[1]
            elif systemic and (s := sc.shock("systemic", "pd_mult")):
                mult, source, ch_name, reason = s[0], s[1], "market", f"{pos['id']}: systemic PD stress"
            pd_s = min(1.0, pos["pd"] * mult)
            stage = self._stage(pos, pd_s, sc, channel)
            ecl0, ecl1 = self._ecl(pos, pos["pd"], pos.get("stage", 1)), self._ecl(pos, pd_s, stage)
            if source or stage != pos.get("stage", 1):
                note = f"; stage {pos.get('stage', 1)} -> {stage}" if stage != pos.get("stage", 1) else ""
                add(ch_name or channel[0], (reason or channel[1]) + note, "PD multiplier (IFRS 9 ECL)", mult, "x",
                    source or "hard flag", pos["ead"] * pos["lgd"], -(ecl1 - ecl0))
            after = {"pd": pd_s, "stage": stage, "ecl_before": ecl0, "ecl_after": ecl1,
                     "grade": self._grade_for(pd_s)}
        return paths, after

    def _stage(self, pos: dict, pd_s: float, sc: Scenario, channel) -> int:
        if channel and channel[0] == "direct" and any(f in ("1.03", "bankruptcy") for f in sc.hard_flags):
            return 3
        if pd_s >= STAGE2_PD_MULTIPLE * pos["pd_origination"] or pd_s >= STAGE2_PD_ABSOLUTE:
            return 2
        if channel and channel[0] == "direct" and any(f in ("2.04", "4.02") for f in sc.hard_flags):
            return 2
        return pos.get("stage", 1)

    @staticmethod
    def _ecl(pos: dict, pd: float, stage: int) -> float:
        if stage == 3:
            return pos["lgd"] * pos["ead"]
        horizon_pd = lifetime_pd(pd, pos["maturity_years"]) if stage == 2 else pd
        return horizon_pd * pos["lgd"] * pos["ead"]

    def _grade_for(self, pd: float) -> str:
        return min(self.grades, key=lambda g: abs(math.log(self.grades[g]["pd"]) - math.log(max(pd, 1e-6))))

    # ---- run ------------------------------------------------------------------------------------
    def _rwa(self, pos: dict, grade: str | None = None, value: float | None = None) -> float:
        """Risk-weighted amount of one position (A-22): loans EAD x grade weight, swaps notional x weight,
        equities and bonds/options market value x weight. The same function prices before and after."""
        if pos["type"] in ("sme_loan", "corporate_loan"):
            return pos["ead"] * self.grades[grade or pos["grade"]]["risk_weight"]
        if pos["type"] == "swap":
            return pos["notional"] * pos["risk_weight"]
        mv = pos["market_value"] if value is None else value
        weight = self.equity_rw if pos["type"] == "equity" else pos["risk_weight"]
        return max(0.0, mv) * weight

    def run(self, sc: Scenario, include_positions: bool = True) -> dict:
        positions = self.book["tranche1"] + self.book["tranche2"]
        tax = self.capital["tax_rate"]
        rows, total = [], 0.0
        ecl = {"before": {1: 0.0, 2: 0.0, 3: 0.0}, "after": {1: 0.0, 2: 0.0, 3: 0.0}}
        migrations, unaffected = [], {}
        rwa_before = rwa_after = rwa_migration = rwa_value = 0.0
        by_class: dict[str, float] = {}
        for pos in positions:
            paths, after = self._paths(pos, sc)
            dv = sum(p["dv"] for p in paths)
            total += dv
            asset = pos["type"]
            by_class[asset] = by_class.get(asset, 0.0) + dv
            r0 = self._rwa(pos)
            if "ecl_after" in after:
                ecl["before"][pos.get("stage", 1)] += after["ecl_before"]
                ecl["after"][after["stage"]] += after["ecl_after"]
                if after["stage"] != pos.get("stage", 1):
                    migrations.append({"id": pos["id"], "from": pos.get("stage", 1), "to": after["stage"],
                                       "pd_before": pos["pd"], "pd_after": round(after["pd"], 6),
                                       "ecl_increase": round(after["ecl_after"] - after["ecl_before"], 2)})
                r1 = self._rwa(pos, grade=after["grade"])
                rwa_migration += r1 - r0
            else:
                r1 = self._rwa(pos, value=pos.get("market_value", 0.0) + dv)
                rwa_value += r1 - r0
            rwa_before += r0
            rwa_after += r1
            row = {"id": pos["id"], "type": asset, "name": pos.get("name", pos.get("issuer", pos["id"])),
                   "sector": pos.get("sector"), "state": pos.get("state"), "exposure": round(_exposure(pos), 2),
                   "dv": round(dv, 2), "capital_impact": round(dv * (1 - tax), 2),
                   "rwa_before": round(r0, 2), "rwa_after": round(r1, 2), "paths": paths}
            if "ecl_after" in after:
                row.update({"stage_after": after["stage"], "grade_after": after["grade"],
                            "ecl_change": round(after["ecl_after"] - after["ecl_before"], 2)})
            if not paths:
                row["unaffected_reason"] = self._why_not(pos, sc)
                unaffected[row["unaffected_reason"]] = unaffected.get(row["unaffected_reason"], 0) + 1
            rows.append(row)
        cet1_0 = self.capital["cet1"]
        cet1_1 = cet1_0 + total * (1 - tax)
        ecl_0, ecl_1 = sum(ecl["before"].values()), sum(ecl["after"].values())
        result = {
            "scenario": {"name": sc.name, "event_id": sc.event_id, "event_type": sc.event_type,
                         "subtype": sc.subtype, "entity": sc.entity, "sector": sc.sector, "states": sorted(sc.states),
                         "impact": sc.impact, "k": sc.k, "hard_flags": sc.hard_flags,
                         "sector_scope": sc.sector_scope, "layers": sc.layers},
            "pnl_total": round(total, 2),
            "pnl_by_asset_class": {k: round(v, 2) for k, v in by_class.items()},
            "ecl": {s: {str(k): round(v, 2) for k, v in d.items()} for s, d in ecl.items()},
            "ecl_change": round(ecl_1 - ecl_0, 2),
            "stage_migrations": migrations,
            "capital": {
                "cet1_before": round(cet1_0, 2), "cet1_after": round(cet1_1, 2),
                "rwa_before": round(rwa_before, 2), "rwa_after": round(rwa_after, 2),
                "cet1_ratio_before": round(cet1_0 / rwa_before, 5), "cet1_ratio_after": round(cet1_1 / rwa_after, 5),
                "delta": {"cet1": round(cet1_1 - cet1_0, 2), "rwa": round(rwa_after - rwa_before, 2),
                          "cet1_ratio": round(cet1_1 / rwa_after - cet1_0 / rwa_before, 5)},
                "reconciliation": {
                    "cet1": f"CET1 after = CET1 before + P&L x (1 - tax {tax:.0%}); A-12: losses reduce capital "
                            "net of tax",
                    "rwa_change_from_rating_migration": round(rwa_migration, 2),
                    "rwa_change_from_market_values": round(rwa_value, 2),
                    "book_rwa_recorded": self.capital["rwa"],
                },
                "floors": self.capital["floors"],
            },
            "n_positions_affected": sum(1 for r in rows if r["paths"]),
            "unaffected_by_reason": unaffected,
            "top_contributors": sorted((r for r in rows if r["paths"]), key=lambda r: r["dv"])[:10],
        }
        if include_positions:
            result["positions"] = rows
        return result

    def reverse_stress(self, sc: Scenario, floor: float, k_max: float = 10.0) -> dict:
        """Smallest severity multiple (of the severe-end shocks) at which CET1 falls to `floor`."""
        def ratio(k):
            scaled = Scenario(**{**sc.__dict__, "k": k})
            return self.run(scaled, include_positions=False)["capital"]["cet1_ratio_after"]

        if ratio(k_max) > floor:
            return {"floor": floor, "breaks_at_k": None, "note": f"CET1 stays above the floor up to {k_max}x severe"}
        lo, hi = 0.0, k_max
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if ratio(mid) > floor else (lo, mid)
        return {"floor": floor, "breaks_at_k": round(hi, 3),
                "note": f"CET1 reaches {floor:.1%} at {hi:.2f}x the severe-end scenario"}
