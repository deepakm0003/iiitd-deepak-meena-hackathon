"""A portfolio uploaded by the user, built into a book with the same rules as the synthetic demonstration book.

One CSV row per position. Columns (case-insensitive):
  type            loan | bond | equity | sme_loan
  issuer          a tracked ticker for loan / bond / equity (e.g. JPM); any name for sme_loan
  exposure        loan or sme_loan: exposure at default; bond: notional; equity: market value (USD)
  grade           AA | A | BBB | BB | B | CCC (loans and bonds; default BBB)
  sector          optional for tracked tickers (taken from the universe); required for sme_loan
  state           optional, US state code (sme_loan: the geography channel for disasters)
  maturity_years  optional (loans and bonds; default 5)
  coupon          optional (bonds; default: priced at par)
Probability of default and risk weight come from the grade table (assumptions A-05, A-22), bonds are priced off
today's 10-year yield plus the grade spread (A-24), equity uses the standardised 250% risk weight, and capital
starts at 12% of the book's RWA (A-21). The book lives only for the request: nothing is stored.
"""

from tripwire.config import load_yaml
from tripwire.portfolio.book import GRADE_SPREAD_BP
from tripwire.portfolio.pricing import bond_price, duration_convexity

MAX_POSITIONS = 500
TYPES = {"loan": "corporate_loan", "corporate_loan": "corporate_loan", "bond": "bond", "equity": "equity",
         "sme_loan": "sme_loan", "sme": "sme_loan"}


def build_uploaded_book(rows: list[dict], market: dict, universe: dict, cfg: dict | None = None) -> dict:
    """Validate the rows and build the book; raises ValueError listing every row problem."""
    cfg = cfg or load_yaml("book.yaml")
    grades = cfg["grades"]
    if not rows:
        raise ValueError("the portfolio has no rows")
    if len(rows) > MAX_POSITIONS:
        raise ValueError(f"{len(rows)} positions; the limit is {MAX_POSITIONS}")
    rate = market["FRED:DGS10"]["value"] / 100
    errors, sme, corp = [], [], []
    for n, raw in enumerate(rows, 1):
        row = {str(k).strip().lower(): (str(v).strip() if v is not None else "") for k, v in raw.items()}
        kind = TYPES.get(row.get("type", "").lower())
        issuer = row.get("issuer", "").upper() if kind != "sme_loan" else row.get("issuer", "")
        grade = (row.get("grade") or "BBB").upper()
        try:
            exposure = float(row.get("exposure", "").replace(",", ""))
        except ValueError:
            exposure = -1
        problems = []
        if kind is None:
            problems.append(f"type must be one of loan, bond, equity, sme_loan (got {row.get('type')!r})")
        if exposure <= 0:
            problems.append("exposure must be a positive number")
        if kind in ("corporate_loan", "bond", "sme_loan") and grade not in grades:
            problems.append(f"grade must be one of {', '.join(grades)}")
        if kind in ("corporate_loan", "bond", "equity") and issuer not in universe:
            problems.append(f"issuer {issuer!r} is not a tracked ticker (use sme_loan for other borrowers)")
        if kind == "sme_loan" and not row.get("sector"):
            problems.append("sme_loan needs a sector")
        try:
            maturity = float(row.get("maturity_years") or 5)
            coupon = float(row["coupon"]) if row.get("coupon") else None
        except ValueError:
            problems.append("maturity_years and coupon must be numbers")
            maturity, coupon = 5.0, None
        if problems:
            errors.append(f"row {n}: " + "; ".join(problems))
            continue
        pid = f"{kind.upper().replace('_', '-')}-{issuer or n}-{n}"
        sector = row.get("sector") or universe.get(issuer, {}).get("sector", "n/a")
        if kind == "sme_loan":
            sme.append({
                "id": pid, "type": "sme_loan", "name": issuer or f"Borrower {n}", "sector": sector,
                "state": (row.get("state") or "").upper() or None, "grade": grade, "pd": grades[grade]["pd"],
                "pd_origination": grades[grade]["pd"], "lgd": cfg["tranche1"]["lgd"], "ead": exposure,
                "maturity_years": maturity, "stage": 1, "risk_weight": grades[grade]["risk_weight"],
            })
        elif kind == "corporate_loan":
            corp.append({
                "id": pid, "type": "corporate_loan", "issuer": issuer, "sector": sector, "grade": grade,
                "pd": grades[grade]["pd"], "pd_origination": grades[grade]["pd"], "lgd": cfg["tranche1"]["lgd"],
                "ead": exposure, "maturity_years": maturity, "stage": 1, "risk_weight": grades[grade]["risk_weight"],
            })
        elif kind == "bond":
            yld = rate + GRADE_SPREAD_BP[grade] / 1e4
            cpn = coupon if coupon is not None else yld
            price = bond_price(cpn, maturity, yld)
            dur, conv = duration_convexity(cpn, maturity, yld)
            corp.append({
                "id": pid, "type": "bond", "issuer": issuer, "sector": sector, "grade": grade,
                "pd": grades[grade]["pd"], "notional": exposure, "coupon": cpn, "maturity_years": maturity,
                "yield": round(yld, 5), "price": round(price, 6), "market_value": round(price * exposure, 2),
                "duration": round(dur, 4), "convexity": round(conv, 4), "risk_weight": grades[grade]["risk_weight"],
            })
        else:
            corp.append({
                "id": pid, "type": "equity", "issuer": issuer, "sector": sector, "market_value": exposure,
                "spot": market.get(issuer, {}).get("value"), "risk_weight": cfg["capital"]["equity_risk_weight"],
            })
    if errors:
        raise ValueError("; ".join(errors[:20]) + (f"; and {len(errors) - 20} more" if len(errors) > 20 else ""))
    rwa = sum(o["ead"] * o["risk_weight"] for o in sme)
    rwa += sum((p.get("ead") or p["market_value"]) * p["risk_weight"] for p in corp)
    cet1 = cfg["capital"]["cet1_ratio_start"] * rwa
    return {
        "as_of": "uploaded",
        "description": "Your uploaded portfolio, built with the demonstration book's assumptions (A-05, A-21, A-22, "
                       "A-24). Not stored.",
        "market_snapshot": market,
        "tranche1": sme,
        "tranche2": corp,
        "capital": {"rwa": round(rwa, 2), "cet1": round(cet1, 2), "cet1_ratio": cfg["capital"]["cet1_ratio_start"],
                    "floors": cfg["capital"]["floors"], "tax_rate": cfg["capital"]["tax_rate"]},
        "totals": {"tranche1_ead": round(sum(o["ead"] for o in sme), 2),
                   "tranche2_exposure": round(sum(p.get("ead") or p.get("market_value", 0) for p in corp), 2)},
    }
