"""Measured market inputs for the stress engine: historical-analog moves and equity betas.

Both are MEASURED from the price cache (public data) and saved to data/market_inputs.json, so the stress
engine and the README Quickstart never need live market data.
"""

from datetime import date, timedelta

from tripwire.config import load_yaml


def _close_on_or_before(series: dict[date, float], day: date) -> tuple[date, float]:
    for i in range(10):
        d = day - timedelta(days=i)
        if d in series:
            return d, series[d]
    raise KeyError(f"no observation within 10 days before {day}")


def measure_analogs(prices: dict[str, dict[date, float]], cfg: dict | None = None) -> dict:
    cfg = cfg or load_yaml("analogs.yaml")
    durations = cfg["etf_duration"]
    out = {}
    for event_class, w in cfg["windows"].items():
        start, end = date.fromisoformat(str(w["start"])), date.fromisoformat(str(w["end"]))

        def ret(ticker: str, start=start, end=end) -> float:
            s = prices[ticker]
            return _close_on_or_before(s, end)[1] / _close_on_or_before(s, start)[1] - 1

        def level_change_bp(ticker: str, start=start, end=end) -> float:
            s = prices[ticker]
            return (_close_on_or_before(s, end)[1] - _close_on_or_before(s, start)[1]) * 100  # percent -> bp

        out[event_class] = {
            "name": w["name"], "start": str(start), "end": str(end),
            "equity_market": round(ret("SPY"), 4),
            "sector_etf": w["sector_etf"], "equity_sector": round(ret(w["sector_etf"]), 4),
            "rate_10y_bp": round(level_change_bp("FRED:DGS10"), 1),
            "ig_spread_bp": round(-(ret("LQD") - 0) / durations["LQD"] * 1e4 - level_change_bp("FRED:DGS10"), 1),
            "hy_spread_bp": round(-ret("HYG") / durations["HYG"] * 1e4 - level_change_bp("FRED:DGS10"), 1),
            "vol_pts": round(_close_on_or_before(prices["FRED:VIXCLS"], end)[1]
                             - _close_on_or_before(prices["FRED:VIXCLS"], start)[1], 2),
        }
    return out


def measure_betas(prices: dict[str, dict[date, float]], tickers: list[str], sector_etf: dict[str, str],
                  window_days: int = 504) -> dict[str, dict]:
    """OLS betas of daily returns on SPY and on the sector ETF over the last ~2 years."""
    from tripwire.scoring.event_study import returns

    spy = returns(prices["SPY"])
    days = sorted(spy)[-window_days:]
    out = {}
    for ticker in tickers:
        if ticker not in prices:
            continue
        r = returns(prices[ticker])
        etf = sector_etf.get(ticker)
        out[ticker] = {"beta_market": round(_beta(r, spy, days), 4)}
        if etf and etf in prices:
            out[ticker]["sector_etf"] = etf
            out[ticker]["beta_sector"] = round(_beta(r, returns(prices[etf]), days), 4)
    return out


def _beta(y: dict, x: dict, days: list) -> float:
    pairs = [(x[d], y[d]) for d in days if d in x and d in y]
    if len(pairs) < 60:
        return 1.0
    mx = sum(p[0] for p in pairs) / len(pairs)
    my = sum(p[1] for p in pairs) / len(pairs)
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    return sum((p[0] - mx) * (p[1] - my) for p in pairs) / sxx if sxx else 1.0
