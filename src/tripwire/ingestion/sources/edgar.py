"""SEC EDGAR 8-K filings for the universe, from the submissions API (data.sec.gov/submissions/CIK##########.json).

Each filing carries its exact acceptanceDateTime and its 8-K item numbers: the cleanest timestamps and the
strongest weak labels we have (used by the event study and the event classifier). SEC requires a descriptive
User-Agent with contact details and allows 10 requests/second; we use 5.
Cursor: {cik: newest acceptanceDateTime seen (ISO)}.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from tripwire.ingestion.http import HttpClient, HttpError
from tripwire.models import RawDocument
from tripwire.ports.source import FetchResult
from tripwire.universe import Company

log = logging.getLogger(__name__)
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"


def parse_sec_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def filing_title(company_name: str, form: str, items: list[str], item_names: dict[str, str]) -> str:
    shown = [i for i in items if i != "9.01"] or items  # 9.01 (exhibits) only adds noise unless alone
    parts = [f"Item {i} {item_names.get(i, '')}".strip() for i in shown]
    return f"{company_name} files {form}" + (": " + "; ".join(parts) if parts else "")


class EdgarSource:
    name = "edgar"
    source_type = "filing"

    def __init__(
        self,
        http: HttpClient,
        companies: list[Company],
        item_names: dict[str, str],
        cfg: dict[str, Any],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.http = http
        self.companies = [c for c in companies if c.cik]
        self.item_names = item_names
        self.forms = set(cfg.get("forms", ["8-K", "8-K/A"]))
        self.lookback = timedelta(days=int(cfg.get("initial_lookback_days", 7)))
        self._now = now

    def fetch(self, cursor: str | None) -> FetchResult:
        state: dict[str, str] = json.loads(cursor) if cursor else {}
        default_since = self._now() - self.lookback
        documents: list[RawDocument] = []
        failures = 0
        for company in self.companies:
            key = str(company.cik)
            since = parse_sec_time(state[key]) if key in state else default_since
            try:
                recent = self.http.get(SUBMISSIONS.format(cik=company.cik)).json()["filings"]["recent"]
            except (HttpError, KeyError, ValueError) as exc:
                failures += 1
                log.warning("edgar %s failed: %s", company.ticker, exc)
                continue
            newest = since
            for i, form in enumerate(recent.get("form", [])):
                if form not in self.forms:
                    continue
                accepted = parse_sec_time(recent["acceptanceDateTime"][i])
                if accepted <= since:
                    continue
                documents.append(self._doc(company, recent, i, form, accepted))
                newest = max(newest, accepted)
            state[key] = newest.isoformat()
        if self.companies and failures == len(self.companies):
            raise RuntimeError("all EDGAR submissions requests failed")
        return FetchResult(documents, json.dumps(state))

    def _doc(self, company: Company, recent: dict, i: int, form: str, accepted: datetime) -> RawDocument:
        accession = recent["accessionNumber"][i]
        items = [x.strip() for x in (recent.get("items", [""] * (i + 1))[i] or "").split(",") if x.strip()]
        document = recent.get("primaryDocument", [""] * (i + 1))[i]
        url = ARCHIVE.format(cik=company.cik, accession=accession.replace("-", ""), document=document)
        return RawDocument(
            source=self.name,
            source_type="filing",
            title=filing_title(company.sec_name or company.ticker, form, items, self.item_names),
            url=url if document else None,
            external_id=accession,
            published_at=accepted,
            payload={
                "cik": company.cik,
                "ticker": company.ticker,
                "form": form,
                "items": items,
                "accession": accession,
                "primary_document": document,
                "report_date": recent.get("reportDate", [""] * (i + 1))[i],
                "sic": company.sic,
            },
        )
