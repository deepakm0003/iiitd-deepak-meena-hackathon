"""Assemble the synthetic wholesale book (Module B) from the dataset-derived merchant table and book.yaml.

Provenance per field: DERIVED (from the transaction data), SYNTHETIC (generated terms), ASSUMPTION
(parameters in config/book.yaml), OBSERVED (market snapshot from the price cache).
"""

import hashlib
import json
from datetime import date
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.portfolio.pricing import bond_price, bs_put, duration_convexity, swap_dv01

# What the SME behavioural score is, and is not (docs/module_b.md section 2).
RISK_SCORE_MEANING = ("MODEL: calibrated probability that card volume collapses next year (a proxy event, validated "
                      "out of time); used to rank obligors into grades. Not a probability of default: loan PDs come "
                      "from the grade table, ASSUMPTION A-05")
GRADE_SPREAD_BP = {"AA": 50, "A": 80, "BBB": 130, "BB": 250, "B": 450, "CCC": 900}  # A-24
SECTOR_ETF = {
    "Information Technology": "XLK", "Communication Services": "XLC", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Health Care": "XLV", "Financials": "XLF", "Industrials": "XLI", "Energy": "XLE",
    "Utilities": "XLU", "Materials": "XLB", "Real Estate": "XLRE",
}


# ------------------------------------------------------------------------------------------- merchants
def build_merchant_table(derived_dir: Path, sector_map_csv: Path, fy: int, label_years=(2015, 2016, 2017, 2018)):
    """Features for the as-of year plus a risk probability from the model refit on all labelled years."""
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from tripwire.portfolio import merchants as m

    monthly = pd.read_pickle(derived_dir / "monthly.pkl")
    customers = pd.read_pickle(derived_dir / "customers.pkl")
    states = pd.read_pickle(derived_dir / "states.pkl")
    mccs = pd.read_pickle(derived_dir / "mccs.pkl")
    parts = [m.features(monthly, customers, y) for y in label_years]
    x = pd.concat(parts)
    y = pd.concat([m.distress_outcome(monthly, yr, p.index) for yr, p in zip(label_years, parts, strict=True)])
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(
        x[m.FEATURES], y)
    table = m.features(monthly, customers, fy)
    table["risk_score"] = model.predict_proba(table[m.FEATURES])[:, 1]
    sectors = pd.read_csv(sector_map_csv).set_index("mcc")["sector"]
    table["mcc"] = m.main_mcc(mccs).reindex(table.index)
    table["sector"] = table["mcc"].map(sectors).fillna("Consumer Discretionary")
    table["state"] = m.home_state(states).reindex(table.index)
    keep = ["sector", "mcc", "state", "volume", "prior_volume", "customers", "active_months", *m.FEATURES,
            "risk_score"]
    return table[keep].round(6)


# ------------------------------------------------------------------------------------------- helpers
def cap_weights(weights: list[float], cap: float) -> list[float]:
    """Water-filling: no weight above `cap`, excess redistributed pro rata to the uncapped names."""
    w = [x / sum(weights) for x in weights]
    for _ in range(100):
        over = [i for i, x in enumerate(w) if x > cap + 1e-12]
        if not over:
            break
        excess = sum(w[i] - cap for i in over)
        for i in over:
            w[i] = cap
        free = [i for i, x in enumerate(w) if x < cap - 1e-12]
        free_total = sum(w[i] for i in free)
        for i in free:
            w[i] += excess * w[i] / free_total
    return w


def _maturity(merchant_id: int, lo: int, hi: int) -> int:
    """Deterministic synthetic maturity from the id (reproducible, no randomness)."""
    return lo + int(hashlib.sha256(str(merchant_id).encode()).hexdigest(), 16) % (hi - lo + 1)


def market_snapshot(store, tickers: list[str]) -> dict:
    """Latest cached observation per ticker (OBSERVED), plus rates and volatility."""
    snap = {}
    for t in [*tickers, "SPY", "FRED:DGS10", "FRED:VIXCLS"]:
        bars = store.get_prices(t)
        if bars:
            snap[t] = {"value": bars[-1].adj_close, "date": bars[-1].date.isoformat()}
    return snap


# ------------------------------------------------------------------------------------------- book
def build_book(merchant_rows: list[dict], market: dict, universe: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_yaml("book.yaml")
    t1, grades = cfg["tranche1"], cfg["grades"]
    rate = market["FRED:DGS10"]["value"] / 100

    # Tranche 1: SME obligors, largest card volume first.
    top = sorted(merchant_rows, key=lambda r: -r["volume"])[: t1["n_obligors"]]
    weights = cap_weights([r["volume"] * t1["facility_multiple"] for r in top], t1["single_obligor_cap"])
    by_risk = sorted(range(len(top)), key=lambda i: top[i]["risk_score"])  # safest first
    grade_of = {}
    cursor = 0
    for grade, share in t1["grade_distribution"].items():
        n = round(share * len(top))
        for i in by_risk[cursor : cursor + n]:
            grade_of[i] = grade
        cursor += n
    for i in by_risk[cursor:]:
        grade_of[i] = list(t1["grade_distribution"])[-1]
    obligors = []
    for i, row in enumerate(top):
        grade = grade_of[i]
        obligors.append({
            "id": f"SME-{int(row['merchant_id'])}",
            "type": "sme_loan",
            "name": f"Merchant-{int(row['merchant_id'])} ({row['sector']}, {row['state']})",
            "sector": row["sector"], "state": row["state"], "mcc": int(row["mcc"]),
            "card_volume": round(row["volume"], 2), "risk_score": round(row["risk_score"], 6),
            "grade": grade, "pd": grades[grade]["pd"], "pd_origination": grades[grade]["pd"],
            "lgd": t1["lgd"], "ead": round(weights[i] * t1["total_ead"], 2),
            "maturity_years": _maturity(int(row["merchant_id"]), *t1["maturity_years"]),
            "stage": 1, "risk_weight": grades[grade]["risk_weight"],
            "provenance": {"sector": "DERIVED", "state": "DERIVED", "card_volume": "DERIVED",
                           "risk_score": RISK_SCORE_MEANING, "grade": "ASSUMPTION:A-04",
                           "pd": "ASSUMPTION:A-05", "ead": "SYNTHETIC (A-02, A-11)", "maturity_years": "SYNTHETIC"},
        })

    # Tranche 2: large-corporate positions on public names.
    t2, positions = cfg["tranche2"], []
    for b in t2["bonds"]:
        yld = rate + GRADE_SPREAD_BP[b["grade"]] / 1e4
        price = bond_price(b["coupon"], b["maturity_years"], yld)
        dur, conv = duration_convexity(b["coupon"], b["maturity_years"], yld)
        positions.append({
            "id": f"BOND-{b['issuer']}", "type": "bond", "issuer": b["issuer"],
            "sector": universe[b["issuer"]]["sector"], "grade": b["grade"], "pd": grades[b["grade"]]["pd"],
            "notional": b["notional"], "coupon": b["coupon"], "maturity_years": b["maturity_years"],
            "yield": round(yld, 5), "price": round(price, 6), "market_value": round(price * b["notional"], 2),
            "duration": round(dur, 4), "convexity": round(conv, 4), "risk_weight": grades[b["grade"]]["risk_weight"],
        })
    for ln in t2["loans"]:
        positions.append({
            "id": f"LOAN-{ln['borrower']}", "type": "corporate_loan", "issuer": ln["borrower"],
            "sector": universe[ln["borrower"]]["sector"], "grade": ln["grade"], "pd": grades[ln["grade"]]["pd"],
            "pd_origination": grades[ln["grade"]]["pd"], "lgd": t1["lgd"], "ead": ln["ead"],
            "maturity_years": ln["maturity_years"], "stage": 1, "risk_weight": grades[ln["grade"]]["risk_weight"],
        })
    for e in t2["equities"]:
        sector = universe.get(e["ticker"], {}).get("sector", "Financials")
        positions.append({
            "id": f"EQ-{e['ticker']}", "type": "equity", "issuer": e["ticker"], "sector": sector,
            "market_value": e["market_value"], "spot": market.get(e["ticker"], {}).get("value"),
            "risk_weight": cfg["capital"]["equity_risk_weight"],
        })
    for s in t2["swaps"]:
        dv01 = swap_dv01(s["notional"], s["tenor_years"], rate)
        positions.append({
            "id": s["id"], "type": "swap", "side": s["side"], "notional": s["notional"],
            "tenor_years": s["tenor_years"], "fixed_rate": round(rate, 5), "market_value": 0.0,
            "dv01": round(dv01 if s["side"] == "receive_fixed" else -dv01, 2), "risk_weight": 0.02,
        })
    spot, vol = market["SPY"]["value"], market["FRED:VIXCLS"]["value"] / 100
    for p in t2["index_puts"]:
        strike = p["moneyness"] * spot
        units = p["notional"] / spot
        premium = bs_put(spot, strike, p["expiry_years"], vol, rate)
        positions.append({
            "id": p["id"], "type": "index_put", "underlying": p["underlying"], "units": round(units, 4),
            "strike": round(strike, 4), "expiry_years": p["expiry_years"], "spot": spot, "vol": round(vol, 4),
            "market_value": round(premium * units, 2), "notional": p["notional"], "risk_weight": 1.0,
        })

    rwa = sum(o["ead"] * o["risk_weight"] for o in obligors)
    for p in positions:
        exposure = p.get("ead") or (p["notional"] if p["type"] == "swap" else p["market_value"])
        rwa += exposure * p["risk_weight"]
    cet1 = cfg["capital"]["cet1_ratio_start"] * rwa
    return {
        "as_of": date.today().isoformat(),
        "description": "Synthetic wholesale book: SME loans derived from the Kaggle card-transaction data "
                       "(Tranche 1) and synthetic large-corporate positions on public names (Tranche 2).",
        "market_snapshot": market,
        "tranche1": obligors,
        "tranche2": positions,
        "capital": {"rwa": round(rwa, 2), "cet1": round(cet1, 2), "cet1_ratio": cfg["capital"]["cet1_ratio_start"],
                    "floors": cfg["capital"]["floors"], "tax_rate": cfg["capital"]["tax_rate"]},
        "totals": {"tranche1_ead": round(sum(o["ead"] for o in obligors), 2),
                   "tranche2_exposure": round(sum(p.get("ead") or p.get("market_value", 0) for p in positions), 2)},
    }


def save_book(book: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1), encoding="utf-8")
