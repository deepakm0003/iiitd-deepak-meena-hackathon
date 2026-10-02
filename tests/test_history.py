from datetime import UTC, date, datetime

import httpx

from helpers import COMPANIES, fake_http
from tripwire.ingestion.filing_text import fetch_filing_text, html_to_text, pick_exhibit
from tripwire.ingestion.sources.edgar import EdgarSource
from tripwire.market.prices import fetch_fred
from tripwire.models import FilingText, PriceBar


def _page(accessions, forms, times):
    return {
        "accessionNumber": accessions,
        "form": forms,
        "acceptanceDateTime": times,
        "items": ["2.02"] * len(forms),
        "primaryDocument": [f"{a}.htm" for a in accessions],
        "reportDate": [""] * len(forms),
    }


def test_backfill_reads_older_pages_listed_under_files():
    recent = _page(["a3"], ["8-K"], ["2026-09-01T12:00:00.000Z"])
    older = _page(["a2", "a1"], ["8-K", "8-K"], ["2024-05-01T12:00:00.000Z", "2022-06-01T12:00:00.000Z"])
    ancient_requested = []

    def handler(request):
        path = request.url.path
        if path.endswith("CIK0000019617.json"):
            return httpx.Response(200, json={"filings": {"recent": recent, "files": [
                {"name": "CIK0000019617-submissions-001.json", "filingFrom": "2022-01-01", "filingTo": "2024-12-31"},
                {"name": "CIK0000019617-submissions-002.json", "filingFrom": "2015-01-01", "filingTo": "2021-12-31"},
            ]}})
        if path.endswith("-001.json"):
            return httpx.Response(200, json=older)
        ancient_requested.append(path)
        return httpx.Response(500)

    source = EdgarSource(fake_http(handler), COMPANIES[:1], {"2.02": "Results"}, {"forms": ["8-K"]},
                         now=lambda: datetime(2026, 10, 2, tzinfo=UTC))
    docs = source.backfill(datetime(2023, 1, 1, tzinfo=UTC))
    assert sorted(d.external_id for d in docs) == ["a2", "a3"]   # a1 is before 'since'
    assert ancient_requested == []                                 # pages ending before 'since' are skipped


def test_html_to_text_drops_hidden_xbrl_and_keeps_paragraphs():
    markup = """<html><body><ix:header><ix:hidden>dei:EntityCentralIndexKey 0000019617</ix:hidden></ix:header>
    <script>var x=1;</script><p>Item 2.02&nbsp;Results of Operations</p><div>Net income rose <b>12%</b>.</div>
    </body></html>"""
    assert html_to_text(markup) == "Item 2.02 Results of Operations\nNet income rose 12% ."


def test_pick_exhibit_prefers_99_1():
    names = ["jpm-20260714.htm", "jpm-20260714xex992.htm", "jpm-20260714xex991.htm", "R1.htm", "Financial_Report.xlsx"]
    assert pick_exhibit(names) == "jpm-20260714xex991.htm"
    assert pick_exhibit(["d1dex99.htm"]) == "d1dex99.htm"
    assert pick_exhibit(["d1dex101.htm", "x.xml"]) is None


def test_fetch_filing_text_main_and_exhibit():
    def handler(request):
        path = request.url.path
        if path.endswith("index.json"):
            return httpx.Response(200, json={"directory": {"item": [{"name": "main.htm"}, {"name": "ex991.htm"}]}})
        if path.endswith("main.htm"):
            return httpx.Response(200, text="<p>See Exhibit 99.1</p>")
        return httpx.Response(200, text="<p>Bank reports quarterly loss.</p>")

    row = fetch_filing_text(fake_http(handler), 19617, "0000019617-26-000300", "main.htm")
    assert (row.status, row.main_text, row.exhibit_name, row.exhibit_text) == (
        "ok", "See Exhibit 99.1", "ex991.htm", "Bank reports quarterly loss."
    )


def test_fetch_filing_text_records_errors():
    row = fetch_filing_text(fake_http(lambda r: httpx.Response(404)), 1, "0000000001-26-000001", "x.htm")
    assert row.status == "error" and "404" in row.error


def test_filing_texts_and_missing_list(store, make_doc):
    store.add_raw(make_doc(source="edgar", source_type="filing", url=None, external_id="acc-1",
                           payload={"cik": 19617, "primary_document": "a.htm"}))
    store.add_raw(make_doc(source="edgar", source_type="filing", url=None, external_id="acc-2",
                           payload={"cik": 19617, "primary_document": "b.htm"}))
    now = datetime.now(UTC)
    store.add_filing_text(FilingText(accession="acc-1", cik=19617, main_text="x", fetched_at=now))
    store.add_filing_text(FilingText(accession="acc-2", cik=19617, fetched_at=now, status="error", error="boom"))
    assert [m["accession"] for m in store.edgar_filings_missing_text()] == ["acc-2"]   # errors are retried
    store.add_filing_text(FilingText(accession="acc-2", cik=19617, main_text="y", fetched_at=now))  # upsert
    assert store.edgar_filings_missing_text() == []
    assert store.get_filing_text("acc-2").main_text == "y"


def test_prices_upsert_and_coverage(store):
    bars = [PriceBar(ticker="SPY", date=date(2026, 9, 30), adj_close=700.0, source="yahoo"),
            PriceBar(ticker="SPY", date=date(2026, 10, 1), adj_close=701.0, source="yahoo")]
    assert store.upsert_prices(bars) == 2
    store.upsert_prices([PriceBar(ticker="SPY", date=date(2026, 10, 1), adj_close=702.5, source="yahoo")])
    assert [b.adj_close for b in store.get_prices("SPY")] == [700.0, 702.5]
    assert store.price_coverage()["SPY"] == ("2026-09-30", "2026-10-01", 2)


def test_fred_csv_parsing_skips_missing_values():
    csv_text = "observation_date,DGS10\n2021-12-31,1.52\n2022-01-03,1.63\n2022-01-17,.\n2022-01-18,1.87\n"
    bars = fetch_fred(fake_http(lambda r: httpx.Response(200, text=csv_text)), "DGS10", date(2022, 1, 1))
    assert [(b.ticker, str(b.date), b.adj_close) for b in bars] == [
        ("FRED:DGS10", "2022-01-03", 1.63), ("FRED:DGS10", "2022-01-18", 1.87)
    ]
