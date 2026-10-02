"""Cheap, deterministic company matching used by collectors to decide what to keep.

This is a recall-oriented pre-filter, not the entity linker (Part 2 does linking with confidence and NIL).
Rules: all-caps aliases (UPS, AMD, IBM) match case-sensitively so "ups and downs" is not UPS; other aliases
match case-insensitively on word boundaries; cashtags ($JPM, $BRK.B) match universe tickers only.
"""

import re
from collections.abc import Iterable

from tripwire.universe import Company

CASHTAG = re.compile(r"(?<![\w$])\$([A-Z]{1,5}(?:\.[A-Z])?)\b")


def _pattern(alias: str) -> str:
    return r"(?<![\w&])" + re.escape(alias) + r"(?![\w&])"


class NameMatcher:
    def __init__(self, companies: Iterable[Company]) -> None:
        self.companies = list(companies)
        self.tickers = {c.ticker for c in self.companies}
        self._org_index: dict[str, str] = {}
        exact, folded = [], []
        self._alias_to_ticker: dict[str, str] = {}
        for company in self.companies:
            for name in company.all_names:
                self._org_index.setdefault(name.casefold(), company.ticker)
                key = name if name.isupper() else name.casefold()
                self._alias_to_ticker.setdefault(key, company.ticker)
                (exact if name.isupper() else folded).append(name)
        by_length = lambda names: sorted(set(names), key=len, reverse=True)  # noqa: E731
        self._exact = re.compile("|".join(_pattern(a) for a in by_length(exact))) if exact else None
        self._folded = (
            re.compile("|".join(_pattern(a) for a in by_length(folded)), re.IGNORECASE) if folded else None
        )

    def org_lookup(self, org_name: str) -> str | None:
        """Exact (case-insensitive) match of an extracted organisation name, e.g. a GDELT GKG org."""
        return self._org_index.get(org_name.strip().casefold())

    def find(self, text: str) -> set[str]:
        """Tickers whose alias appears in free text."""
        found: set[str] = set()
        if self._exact:
            found |= {self._alias_to_ticker[m.group()] for m in self._exact.finditer(text)}
        if self._folded:
            found |= {self._alias_to_ticker[m.group().casefold()] for m in self._folded.finditer(text)}
        return found

    def cashtags(self, text: str) -> set[str]:
        tickers = {m.group(1).replace(".", "-") for m in CASHTAG.finditer(text)}
        return tickers & self.tickers
