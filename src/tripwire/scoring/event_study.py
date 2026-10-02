"""Event study (MacKinlay 1997): did the market react abnormally to a firm-specific event?

For each event with a ticker and an exact timestamp (8-K acceptanceDateTime):
  t0          first trading session that can react: same day if accepted before 16:00 New York time on a
              trading day, otherwise the next trading day (after-close filings are a classic leak).
  estimation  OLS  R_i = a + b * R_SPY  over trading days [-250, -30] relative to t0 (needs >= 120 days)
  abnormal    AR_t = R_i,t - (a + b * R_SPY,t)
  target      SCAR = (AR_0 + AR_1) / (sigma_e * sqrt(2))   standardised two-day cumulative abnormal return
  large move  |SCAR| > 1.96
Confounders: events of the same ticker within +-2 trading days of each other are dropped (reported count),
because their returns cannot be attributed to one event. Same-day filings are merged first.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 0)
EST_START, EST_END, MIN_EST_DAYS = -250, -30, 120
LARGE_MOVE = 1.96


@dataclass
class EventReturn:
    event_key: str
    ticker: str
    t0: date
    car: float
    scar: float
    sigma: float
    beta: float
    n_est: int

    @property
    def large(self) -> bool:
        return abs(self.scar) > LARGE_MOVE


def reaction_day(ts: datetime, trading_days: list[date]) -> date | None:
    """First trading day whose session can react to news published at `ts`."""
    local = ts.astimezone(NY)
    day = local.date()
    if local.time() >= MARKET_CLOSE:
        return next((d for d in trading_days if d > day), None)
    return next((d for d in trading_days if d >= day), None)


def returns(prices: dict[date, float]) -> dict[date, float]:
    days = sorted(prices)
    return {d: prices[d] / prices[p] - 1 for p, d in zip(days, days[1:], strict=False) if prices[p] > 0}


def market_model(
    stock: dict[date, float], market: dict[date, float], days: list[date]
) -> tuple[float, float, float, int]:
    xs, ys = [], []
    for d in days:
        if d in stock and d in market:
            xs.append(market[d])
            ys.append(stock[d])
    n = len(xs)
    if n < MIN_EST_DAYS:
        return 0.0, 0.0, 0.0, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx if sxx else 0.0
    alpha = my - beta * mx
    resid = [y - (alpha + beta * x) for x, y in zip(xs, ys, strict=True)]
    sigma = math.sqrt(sum(r * r for r in resid) / max(1, n - 2))
    return alpha, beta, sigma, n


def drop_confounded(events: list[tuple[str, str, date]], trading_days: list[date], window: int = 2) -> tuple[list, int]:
    """events: (key, ticker, t0). Keep events with no other event of the same ticker within +-window days."""
    index = {d: i for i, d in enumerate(trading_days)}
    by_ticker: dict[str, list[int]] = {}
    for _, ticker, t0 in events:
        by_ticker.setdefault(ticker, []).append(index[t0])
    kept = [
        (key, ticker, t0) for key, ticker, t0 in events
        if not any(0 < abs(i - index[t0]) <= window for i in by_ticker[ticker])
    ]
    return kept, len(events) - len(kept)


def study(events: list[tuple[str, str, datetime]], prices: dict[str, dict[date, float]], market: str = "SPY",
          confound_window: int = 2) -> tuple[list[EventReturn], dict]:
    """events: (event_key, ticker, timestamp). Returns per-event abnormal returns and a summary of exclusions."""
    trading_days = sorted(prices[market])
    index = {d: i for i, d in enumerate(trading_days)}
    mret = returns(prices[market])
    stats = {"input": len(events), "no_prices": 0, "no_reaction_day": 0, "confounded": 0, "short_estimation": 0}
    located = []
    for key, ticker, ts in events:
        if ticker not in prices:
            stats["no_prices"] += 1
            continue
        t0 = reaction_day(ts, trading_days)
        if t0 is None or index[t0] + 1 >= len(trading_days):
            stats["no_reaction_day"] += 1
            continue
        located.append((key, ticker, t0))
    # Several filings by one company on the same reaction day are one event (e.g. 8-K and 8-K/A).
    merged = list({(ticker, t0): (key, ticker, t0) for key, ticker, t0 in located}.values())
    kept, stats["confounded"] = drop_confounded(merged, trading_days, confound_window)
    out = []
    returns_cache: dict[str, dict[date, float]] = {}
    for key, ticker, t0 in kept:
        sret = returns_cache.setdefault(ticker, returns(prices[ticker]))
        i0 = index[t0]
        est_days = trading_days[max(0, i0 + EST_START) : max(0, i0 + EST_END)]
        alpha, beta, sigma, n = market_model(sret, mret, est_days)
        window = trading_days[i0 : i0 + 2]
        if n < MIN_EST_DAYS or sigma == 0 or any(d not in sret or d not in mret for d in window):
            stats["short_estimation"] += 1
            continue
        car = sum(sret[d] - (alpha + beta * mret[d]) for d in window)
        out.append(EventReturn(key, ticker, t0, round(car, 6), round(car / (sigma * math.sqrt(2)), 4),
                               round(sigma, 6), round(beta, 4), n))
    stats["studied"] = len(out)
    stats["large_moves"] = sum(r.large for r in out)
    return out, stats
