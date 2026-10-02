"""Closed-form pricing and sensitivities used by the book and the stress engine."""

import math
from statistics import NormalDist

N = NormalDist()


def bond_price(coupon: float, years: float, yld: float, freq: int = 2) -> float:
    """Price per 1 of face for a fixed-coupon bullet bond."""
    n = max(1, round(years * freq))
    c, y = coupon / freq, yld / freq
    return sum(c / (1 + y) ** t for t in range(1, n + 1)) + 1 / (1 + y) ** n


def duration_convexity(coupon: float, years: float, yld: float, freq: int = 2) -> tuple[float, float]:
    """Modified duration and convexity (annual units) by finite differences on the exact price."""
    h = 1e-4
    p0, up, dn = bond_price(coupon, years, yld, freq), bond_price(coupon, years, yld + h, freq), \
        bond_price(coupon, years, yld - h, freq)
    return (dn - up) / (2 * p0 * h), (up + dn - 2 * p0) / (p0 * h * h)


def swap_dv01(notional: float, tenor: float, rate: float, freq: int = 2) -> float:
    """Value change of a receive-fixed swap for +1bp in rates (negative number); pay-fixed is the opposite."""
    annuity = sum(1 / freq / (1 + rate / freq) ** t for t in range(1, round(tenor * freq) + 1))
    return -notional * annuity * 1e-4


def bs_put(spot: float, strike: float, years: float, vol: float, rate: float = 0.0) -> float:
    if years <= 0 or vol <= 0:
        return max(strike - spot, 0.0)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    return strike * math.exp(-rate * years) * N.cdf(-d2) - spot * N.cdf(-d1)


def lifetime_pd(pd_12m: float, years: float) -> float:
    """Cumulative PD over the remaining life, constant hazard (A-23)."""
    return 1 - (1 - min(pd_12m, 1.0)) ** max(years, 1.0)
