"""Daily prices (Yahoo Finance via yfinance) and rates/spreads (FRED CSV, no key).

Raw prices are cached in the local database only and never committed: Yahoo's terms do not allow
redistribution. The repository ships derived results instead (abnormal returns per event, betas).
Note: FRED's ICE BofA credit-spread series only expose roughly the last three years, so LQD/HYG ETF
prices serve as credit proxies before that.
"""

import csv
import io
import logging
from datetime import date

from tripwire.ingestion.http import HttpClient
from tripwire.models import PriceBar

log = logging.getLogger(__name__)

# Market, sector and credit proxies used as event-study benchmarks and stress-test risk factors.
MARKET_TICKERS = [
    "SPY",                                                                    # US market
    "XLK", "XLC", "XLY", "XLP", "XLV", "XLF", "XLI", "XLE", "XLU", "XLB", "XLRE",  # GICS sectors
    "KRE",                                                                    # regional banks
    "LQD", "HYG", "TLT",                                                      # IG credit, HY credit, long Treasuries
]
FRED_SERIES = ["DGS10", "DGS2", "BAMLC0A0CM", "BAMLH0A0HYM2", "VIXCLS"]
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch_yahoo(tickers: list[str], start: date, chunk: int = 25) -> list[PriceBar]:
    import yfinance as yf  # research dependency (requirements-research.txt)

    bars: list[PriceBar] = []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        frame = yf.download(batch, start=start.isoformat(), auto_adjust=False, progress=False, threads=False)
        if frame.empty:
            log.warning("yahoo returned no data for %s", batch)
            continue
        for ticker in batch:
            try:
                adj, close, volume = frame["Adj Close"][ticker], frame["Close"][ticker], frame["Volume"][ticker]
            except KeyError:
                log.warning("yahoo: no columns for %s", ticker)
                continue
            for day, value in adj.dropna().items():
                bars.append(
                    PriceBar(
                        ticker=ticker,
                        date=day.date(),
                        adj_close=float(value),
                        close=_num(close.get(day)),
                        volume=_num(volume.get(day)),
                        source="yahoo",
                    )
                )
    return bars


def fetch_fred(http: HttpClient, series_id: str, start: date) -> list[PriceBar]:
    text = http.get(FRED_CSV, params={"id": series_id}).text
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header: observation_date,<SERIES>
    bars = []
    for row in reader:
        if len(row) != 2 or row[1] in ("", "."):
            continue
        day = date.fromisoformat(row[0])
        if day >= start:
            bars.append(PriceBar(ticker=f"FRED:{series_id}", date=day, adj_close=float(row[1]), source="fred"))
    return bars


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN -> None
