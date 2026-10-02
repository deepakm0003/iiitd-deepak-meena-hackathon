"""Module B service: run stress tests for signals (automatic or on request) and what-if scenarios, and store them.

Every run records the scenario (with each shock's source), the trigger decision, P&L by position with its
causal paths, IFRS 9 stage migrations, CET1 before and after, and reverse stress against both floors.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.stress.engine import Scenario, StressEngine
from tripwire.stress.ews import watchlist
from tripwire.stress.trigger import custom_scenario, decide, scenario_from_signal

RERUN_IMPACT_DELTA = 0.5  # an automatic run is repeated only if the event's Impact moved this much


class StressService:
    def __init__(self, store, data_dir: Path) -> None:
        self.store = store
        self.book = json.loads((data_dir / "book.json").read_text(encoding="utf-8"))
        self.market = json.loads((data_dir / "market_inputs.json").read_text(encoding="utf-8"))
        self.analogs = self.market.get("analogs", {})
        self.shocks = load_yaml("shocks.yaml")
        self.trigger_cfg = load_yaml("book.yaml")["stress_trigger"]
        self.engine = StressEngine(self.book, self.market)

    # ---- runs -----------------------------------------------------------------------------------
    def _run(self, scenario: Scenario, trigger: str, decision: dict | None = None) -> dict:
        result = self.engine.run(scenario)
        floors = self.book["capital"]["floors"]
        result["reverse_stress"] = {name: self.engine.reverse_stress(scenario, floor) for name, floor in floors.items()}
        result["sensitivity"] = self.sensitivity(scenario)
        run = {"run_id": uuid.uuid4().hex[:16], "trigger": trigger, "event_id": scenario.event_id,
               "created_at": datetime.now(UTC).isoformat(), "book_as_of": self.book.get("as_of"),
               "decision": decision, **result}
        self.store.add_stress_run(run)
        return run

    def sensitivity(self, scenario: Scenario) -> dict:
        """The same scenario at half and at full severe-end severity: a range for shock uncertainty (the shock
        sizes are assumptions or single historical windows), not a probability interval."""
        k = scenario.k
        levels = {"mild": round(k / 2, 4), "base": k, "severe": 1.0 if k < 1.0 else round(1.5 * k, 4)}
        out = {"note": "scenario range for shock-size uncertainty; not a statistical confidence interval"}
        for name, level in levels.items():
            r = self.engine.run(Scenario(**{**scenario.__dict__, "k": level}), include_positions=False)
            out[name] = {"k": level, "pnl_total": r["pnl_total"], "ecl_change": r["ecl_change"],
                         "cet1_after": r["capital"]["cet1_after"], "cet1_ratio_after": r["capital"]["cet1_ratio_after"],
                         "stage_migrations": len(r["stage_migrations"])}
        return out

    def trace(self, signal: dict) -> dict:
        """One object that answers: what happened, how important, why the model thinks so, why it matters to
        this book, and what happens to the bank. Read-only: shows the latest stored run, never starts one."""
        runs = self.store.list_stress_runs(limit=1, event_id=signal["event_id"])
        run = self.store.get_stress_run(runs[0]["run_id"]) if runs else None
        breakdown = signal.get("impact_breakdown", {})
        return {
            "event_id": signal["event_id"],
            "what_happened": {
                "headline": signal.get("headline"), "first_seen_at": signal["first_seen_at"],
                "entity": signal["primary_entity"], "company": signal.get("company"),
                "event_type": signal["event_type"], "event_subtype": signal.get("event_subtype"),
                "event_method": signal.get("event_method"), "factuality": signal.get("factuality"),
                "sentiment_score": signal["sentiment_score"], "direction": signal.get("direction"),
                "corroboration": signal.get("corroboration"), "documents": signal.get("documents", [])[:5],
                "evidence": signal.get("evidence", []),
            },
            "how_important": {
                "impact_score": signal["impact_score"], "p_large_move": signal.get("p_large_move"),
                "confidence": signal.get("confidence"), "risk_level": signal.get("risk_level"),
                "percentile": breakdown.get("percentile"), "factors": breakdown.get("factors"),
                "contributions": breakdown.get("contributions"), "explanation": signal.get("explanation"),
                "provenance": signal.get("provenance"),
            },
            "why_it_matters_to_this_book": self.decision(signal),
            "what_happens_to_the_bank": None if run is None else {
                "run_id": run["run_id"], "trigger": run["trigger"], "created_at": run["created_at"],
                "scenario": {k: run["scenario"][k] for k in ("name", "k", "entity", "sector", "states")},
                "shocks": run["scenario"]["layers"], "pnl_total": run["pnl_total"],
                "pnl_by_asset_class": run["pnl_by_asset_class"], "ecl_change": run.get("ecl_change"),
                "stage_migrations": run["stage_migrations"], "capital": run["capital"],
                "top_contributors": run["top_contributors"][:5], "sensitivity": run.get("sensitivity"),
                "reverse_stress": run.get("reverse_stress"), "n_positions_affected": run["n_positions_affected"],
            },
            "stress_available": signal["event_type"] in self.shocks["classes"],
        }

    def decision(self, signal: dict, max_age_days: float | None = None) -> dict:
        return decide(signal, self.book, self.shocks, self.trigger_cfg, max_age_days=max_age_days)

    def run_event(self, event_id: str) -> dict:
        """On request: run the event's scenario even if the automatic trigger would not (the decision is kept)."""
        signal = self.store.get_signal(event_id)
        if signal is None:
            raise KeyError(event_id)
        if signal["event_type"] not in self.shocks["classes"]:
            raise ValueError(f"{signal['event_type']} events have no stress mapping")
        return self._run(scenario_from_signal(signal, self.analogs, self.shocks), "manual", self.decision(signal))

    def run_custom(self, event_type: str, impact: float, entity: str | None = None, sector: str | None = None,
                   states: list[str] | None = None, hard_flags: list[str] | None = None) -> dict:
        if entity and not sector:
            sector = next((p.get("sector") for p in self.book["tranche2"] if p.get("issuer") == entity), None)
        scenario = custom_scenario(event_type, impact, self.analogs, entity, sector, states, hard_flags, self.shocks)
        return self._run(scenario, "what-if")

    def auto(self, signals: list[dict]) -> list[dict]:
        """Run the stress test for each recent signal that passes the trigger, once per event (or when its
        Impact has moved by RERUN_IMPACT_DELTA since the last automatic run)."""
        out = []
        for signal in signals:
            if signal["event_type"] not in self.shocks["classes"]:
                continue
            d = self.decision(signal, max_age_days=self.trigger_cfg["auto_max_age_days"])
            if not d["trigger"]:
                continue
            previous = [r for r in self.store.list_stress_runs(limit=5, event_id=signal["event_id"])
                        if r["trigger"] == "auto"]
            if previous and abs(previous[0]["impact"] - signal["impact_score"]) < RERUN_IMPACT_DELTA:
                continue
            run = self._run(scenario_from_signal(signal, self.analogs, self.shocks), "auto", d)
            out.append({k: run[k] for k in ("run_id", "event_id", "pnl_total")})
        return out

    # ---- views ----------------------------------------------------------------------------------
    def watchlist(self, signals: list[dict]) -> dict:
        return watchlist(self.book, signals)

    def portfolio(self, include_positions: bool = False) -> dict:
        from tripwire.stress.trigger import position_exposure

        positions = self.book["tranche1"] + self.book["tranche2"]

        def group(key):
            out: dict[str, float] = {}
            for p in positions:
                k = p.get(key) or "n/a"
                out[k] = out.get(k, 0.0) + position_exposure(p)
            return {k: round(v, 2) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}

        summary = {
            "as_of": self.book.get("as_of"), "description": self.book.get("description"),
            "totals": self.book["totals"], "capital": self.book["capital"],
            "n_positions": {"tranche1": len(self.book["tranche1"]), "tranche2": len(self.book["tranche2"])},
            "exposure_by_type": group("type"), "exposure_by_sector": group("sector"),
            "exposure_by_grade": group("grade"), "tranche1_exposure_by_state": {
                k: v for k, v in group("state").items() if k != "n/a"},
            "market_snapshot": self.book.get("market_snapshot"),
            "analogs": self.analogs,
        }
        if include_positions:
            summary["positions"] = positions
        return summary


def load_service(store, data_dir: Path) -> "StressService | None":
    """The service if the book and market inputs exist (built by `book` and `market-inputs`), else None."""
    if (data_dir / "book.json").exists() and (data_dir / "market_inputs.json").exists():
        return StressService(store, data_dir)
    return None
