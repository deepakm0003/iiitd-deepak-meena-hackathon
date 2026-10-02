"""Stress engine: finance invariants and causal paths, on a small hand-built book."""

import pytest

from tripwire.portfolio.book import cap_weights
from tripwire.portfolio.pricing import bond_price, bs_put, duration_convexity, lifetime_pd, swap_dv01
from tripwire.stress.engine import Scenario, StressEngine, build_layers, severity_k
from tripwire.stress.geo import states_from

GRADES = {"AA": {"pd": 0.0002, "risk_weight": 0.2}, "A": {"pd": 0.0005, "risk_weight": 0.5},
          "BBB": {"pd": 0.0015, "risk_weight": 0.75}, "BB": {"pd": 0.006, "risk_weight": 1.0},
          "B": {"pd": 0.03, "risk_weight": 1.5}, "CCC": {"pd": 0.15, "risk_weight": 1.5}}
CFG = {"grades": GRADES, "capital": {"equity_risk_weight": 2.5}}
ANALOGS = {"Credit Event": {"name": "SVB", "start": "2023-03-08", "end": "2023-03-13", "equity_market": -0.034,
                            "sector_etf": "KRE", "equity_sector": -0.23, "rate_10y_bp": -43.0, "ig_spread_bp": 26.0,
                            "hy_spread_bp": 76.0, "vol_pts": 7.4}}
SHOCKS = {"classes": {
    "Credit Event": {"layers": ["entity", "sector", "systemic"],
                     "entity": {"equity": -0.40, "spread_bp": 500, "pd_mult": 5.0},
                     "sector": {"equity": -0.15, "spread_bp": 200, "pd_mult": 2.0},
                     "systemic": {"equity": -0.03, "rate_10y_bp": -10, "ig_spread_bp": 25, "vol_pts": 5}},
    "Natural Disaster/Supply Chain": {"layers": ["sector", "geography"], "sector": {"equity": -0.1},
                                      "geography": {"pd_mult": 1.8}},
}}


def loan(i, state="CA", sector="Consumer Discretionary", grade="BB", issuer=None):
    return {"id": f"L{i}", "type": "sme_loan" if not issuer else "corporate_loan", "issuer": issuer, "state": state,
            "sector": sector, "grade": grade, "pd": GRADES[grade]["pd"], "pd_origination": GRADES[grade]["pd"],
            "lgd": 0.45, "ead": 1_000_000, "maturity_years": 4, "stage": 1, "risk_weight": 1.0, "risk_score": 0.02,
            "name": f"Obligor {i}"}


def book():
    dur, conv = duration_convexity(0.05, 7, 0.06)
    return {
        "tranche1": [loan(1, "FL"), loan(2, "CA"), loan(3, "TX", grade="B")],
        "tranche2": [
            {"id": "BOND-KEY", "type": "bond", "issuer": "KEY", "sector": "Financials", "grade": "BBB",
             "market_value": 1_000_000, "duration": dur, "convexity": conv, "risk_weight": 0.75},
            {"id": "BOND-XOM", "type": "bond", "issuer": "XOM", "sector": "Energy", "grade": "AA",
             "market_value": 1_000_000, "duration": dur, "convexity": conv, "risk_weight": 0.2},
            {"id": "EQ-JPM", "type": "equity", "issuer": "JPM", "sector": "Financials", "market_value": 500_000,
             "risk_weight": 2.5},
            {**loan(9, None, "Financials", "BBB", issuer="KEY")},
            {"id": "SWP", "type": "swap", "side": "receive_fixed", "notional": 10_000_000, "market_value": 0.0,
             "dv01": swap_dv01(10_000_000, 5, 0.05), "risk_weight": 0.02},
            {"id": "PUT", "type": "index_put", "units": 100, "strike": 90.0, "expiry_years": 0.5, "spot": 100.0,
             "vol": 0.2, "market_value": bs_put(100, 90, 0.5, 0.2) * 100, "risk_weight": 1.0},
        ],
        "capital": {"cet1": 1_000_000, "rwa": 8_000_000, "tax_rate": 0.25, "floors": {"basel": 0.07, "rbi": 0.08}},
    }


def engine():
    return StressEngine(book(), {"betas": {"JPM": {"beta_market": 1.0, "beta_sector": 1.2}}}, CFG)


def credit_event(k=1.0):
    return Scenario("Regional bank run", "Credit Event", "liquidity_stress", "KEY", "Financials", set(), 10.0, k,
                    build_layers("Credit Event", "Financials", ANALOGS, SHOCKS), hard_flags=[])


# ----------------------------------------------------------------------------------------- pricing
def test_pricing_basics():
    assert bond_price(0.05, 5, 0.05) == pytest.approx(1.0, abs=1e-9)          # par bond at its own yield
    dur, conv = duration_convexity(0.05, 5, 0.05)
    assert 4.0 < dur < 4.5 and conv > 0
    assert swap_dv01(1_000_000, 5, 0.05) < 0                                   # receive-fixed loses when rates rise
    assert bs_put(100, 90, 0.5, 0.3) > bs_put(100, 90, 0.5, 0.2) > 0             # higher vol, higher put value
    assert lifetime_pd(0.01, 4) == pytest.approx(1 - 0.99 ** 4)


def test_cap_weights_respects_cap_and_sums_to_one():
    w = cap_weights([50, 30, 10, 5, 5] + [1] * 40, cap=0.1)
    assert max(w) <= 0.1 + 1e-9 and sum(w) == pytest.approx(1.0)


def test_severity_scale():
    assert severity_k(7) == pytest.approx(0.4) and severity_k(10) == pytest.approx(1.0)
    assert severity_k(2) == pytest.approx(0.1)


# ----------------------------------------------------------------------------------------- engine
def test_total_equals_sum_of_paths_and_unaffected_positions_are_zero():
    result = engine().run(credit_event())
    paths_total = sum(p["dv"] for r in result["positions"] for p in r["paths"])
    assert result["pnl_total"] == pytest.approx(paths_total, abs=0.05)
    for r in result["positions"]:
        if not r["paths"]:
            assert r["dv"] == 0


def test_channels_explain_who_is_hit_and_why():
    rows = {r["id"]: r for r in engine().run(credit_event())["positions"]}
    key_bond = rows["BOND-KEY"]["paths"]
    assert any(p["channel"] == "direct" and p["factor"] == "entity credit spread" for p in key_bond)
    jpm = rows["EQ-JPM"]["paths"][0]
    assert jpm["channel"] == "sector" and "MEASURED" in jpm["source"]   # KRE analog drives the bank sector move
    xom = rows["BOND-XOM"]["paths"]
    assert {p["channel"] for p in xom} == {"market"}                    # energy issuer: only systemic factors
    assert rows["SWP"]["dv"] > 0                                        # receive-fixed gains as yields fall 43 bp
    assert rows["PUT"]["dv"] > 0                                        # the hedge pays off


def test_direct_loan_migrates_to_stage_2_and_ecl_jumps():
    result = engine().run(credit_event())
    migration = next(m for m in result["stage_migrations"] if m["id"] == "L9")
    assert migration["to"] == 2 and migration["pd_after"] == pytest.approx(0.0015 * 5)
    assert migration["ecl_increase"] > 10 * 0.0015 * 0.45 * 1_000_000   # lifetime ECL: the IFRS 9 cliff


def test_bankruptcy_flag_sends_direct_loan_to_stage_3():
    sc = credit_event()
    sc.hard_flags = ["1.03"]
    rows = {r["id"]: r for r in engine().run(sc)["positions"]}
    assert rows["L9"]["stage_after"] == 3


def test_more_severity_never_reduces_losses_on_the_loan_book():
    e = engine()
    losses = [e.run(credit_event(k))["pnl_by_asset_class"]["corporate_loan"] for k in (0.2, 0.5, 1.0)]
    assert losses[0] >= losses[1] >= losses[2]


def test_zero_severity_changes_nothing():
    result = engine().run(credit_event(0.0))
    assert result["pnl_total"] == pytest.approx(0.0, abs=1e-6) and result["stage_migrations"] == []


def test_geography_channel_hits_only_obligors_in_named_states():
    sc = Scenario("Hurricane", "Natural Disaster/Supply Chain", None, None, None, {"FL"}, 9.0, 1.0,
                  build_layers("Natural Disaster/Supply Chain", None, {}, SHOCKS))
    rows = {r["id"]: r for r in engine().run(sc)["positions"]}
    assert rows["L1"]["paths"][0]["channel"] == "geography" and rows["L1"]["dv"] < 0
    assert rows["L2"]["paths"] == [] and rows["L2"]["dv"] == 0


def test_capital_and_reverse_stress():
    e = engine()
    result = e.run(credit_event())
    cap = result["capital"]
    assert cap["cet1_after"] == pytest.approx(cap["cet1_before"] + result["pnl_total"] * 0.75)
    reverse = e.reverse_stress(credit_event(), floor=0.07)
    if reverse["breaks_at_k"] is not None:
        at = e.run(credit_event(reverse["breaks_at_k"]))["capital"]["cet1_ratio_after"]
        assert at == pytest.approx(0.07, abs=0.002)


def test_states_from_places():
    assert states_from(["Tampa, Florida, United States"], ["USTX"]) == {"FL", "TX"}
    assert states_from(["Washington"]) == set()    # the city / US government, not Washington State


def test_a_large_company_credit_event_does_not_reach_sme_obligors_by_sector_alone():
    b = book()
    b["tranche1"].append(loan(7, "NV", sector="Financials"))
    rows = {r["id"]: r for r in StressEngine(b, {}, CFG).run(credit_event())["positions"]}
    assert rows["L7"]["paths"] == []                       # SME in the same GICS sector: untouched
    sc = credit_event()
    sc.sector_scope = "all"                                 # sector-wide events (regulation) do reach SMEs
    rows = {r["id"]: r for r in StressEngine(b, {}, CFG).run(sc)["positions"]}
    assert rows["L7"]["paths"][0]["channel"] == "sector"


def test_market_wide_layer_only_for_systemic_events():
    from tripwire.stress.engine import systemic_applies

    credit = {"systemic_when": "financials"}
    assert systemic_applies(credit, "WAL", "Financials") and not systemic_applies(credit, "JNJ", "Health Care")
    geo = {"systemic_when": "market_wide"}
    assert systemic_applies(geo, None, None) and not systemic_applies(geo, "NVDA", "Information Technology")
    assert systemic_applies({}, "X", "Energy")                                  # default: always
    shocks = {"classes": {"Credit Event": {**SHOCKS["classes"]["Credit Event"], "systemic_when": "financials"}}}
    assert "systemic" not in build_layers("Credit Event", "Health Care", ANALOGS, shocks, "JNJ")
    assert "systemic" in build_layers("Credit Event", "Financials", ANALOGS, shocks, "WAL")


@pytest.mark.parametrize("k", [0.0, 0.3, 1.0, 3.0])
def test_capital_reconciles_exactly(k):
    """CET1, RWA, ECL and P&L must tie out position by position at any severity."""
    r = engine().run(credit_event(k))
    cap, rows = r["capital"], r["positions"]
    assert cap["cet1_ratio_before"] == pytest.approx(cap["cet1_before"] / cap["rwa_before"], abs=1e-5)
    assert cap["cet1_ratio_after"] == pytest.approx(cap["cet1_after"] / cap["rwa_after"], abs=1e-5)
    assert cap["rwa_before"] == pytest.approx(sum(x["rwa_before"] for x in rows), abs=1)
    assert cap["rwa_after"] == pytest.approx(sum(x["rwa_after"] for x in rows), abs=1)
    rec = cap["reconciliation"]
    assert cap["delta"]["rwa"] == pytest.approx(rec["rwa_change_from_rating_migration"]
                                                + rec["rwa_change_from_market_values"], abs=1)
    assert cap["delta"]["cet1"] == pytest.approx(sum(x["capital_impact"] for x in rows), abs=1)
    assert cap["delta"]["cet1"] == pytest.approx(r["pnl_total"] * 0.75, abs=1)
    loans = [x for x in rows if x["type"] in ("sme_loan", "corporate_loan")]
    assert r["ecl_change"] == pytest.approx(-sum(x["dv"] for x in loans), abs=1)   # loan P&L is the ECL build
    assert r["ecl_change"] == pytest.approx(sum(x["ecl_change"] for x in loans), abs=1)


def test_every_zero_is_explained_and_every_shock_has_a_provenance():
    r = engine().run(credit_event())
    for row in r["positions"]:
        if not row["paths"]:
            assert row["unaffected_reason"]
        for path in row["paths"]:
            assert path["source_type"] in {"HISTORICAL", "ASSUMPTION", "PRICING", "HARD_FLAG"}
    jpm = next(x for x in r["positions"] if x["id"] == "EQ-JPM")["paths"][0]
    assert jpm["source_type"] == "HISTORICAL"                                    # KRE move in the SVB window
    assert sum(r["unaffected_by_reason"].values()) == len(r["positions"]) - r["n_positions_affected"]
