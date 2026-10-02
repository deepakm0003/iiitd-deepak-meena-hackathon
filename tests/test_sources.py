import io
import json
import zipfile
from datetime import UTC, date, datetime

import httpx
import pytest

from helpers import COMPANIES, fake_http
from tripwire.ingestion.matching import NameMatcher
from tripwire.ingestion.sources.bluesky import PostFilter, post_to_document
from tripwire.ingestion.sources.edgar import EdgarSource, filing_title
from tripwire.ingestion.sources.finnhub import FinnhubSource
from tripwire.ingestion.sources.gdelt import GdeltSource, parse_lastupdate
from tripwire.ingestion.sources.rss import RssSource, parse_feed_date

# ---------------------------------------------------------------- GDELT
GDELT_CFG = {
    "base_url": "http://data.gdeltproject.org/gdeltv2",
    "max_files_per_run": 8,
    "macro_orgs": ["federal reserve"],
    "finance_themes": ["ECON_BANKRUPTCY", "ECON_STOCKMARKET"],
    "risk_themes": ["ARMEDCONFLICT"],
    "strong_themes": ["ECON_BANKRUPTCY"],
    "min_theme_hits": 2,
}


def gkg_row(record_id, url, title, orgs="", v2_themes="", v1_themes="", locations="", tone="-4.2,1,5,6,20,2,300"):
    cols = [""] * 27
    cols[0], cols[1], cols[3], cols[4] = record_id, "20261002020000", "example.com", url
    cols[7], cols[8], cols[10], cols[14], cols[15] = v1_themes, v2_themes, locations, orgs, tone
    cols[26] = f"<PAGE_LINKS></PAGE_LINKS><PAGE_TITLE>{title}</PAGE_TITLE>"
    return "\t".join(cols)


def gkg_zip(*rows) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("20261002020000.gkg.csv", "\n".join(rows))
    return buffer.getvalue()


ROWS = [
    gkg_row("1", "https://news.example/jpm", "JPMorgan &amp; peers slide", orgs="Jpmorgan Chase,10;Reuters,40",
            locations="2#Florida, United States#US#USFL##27.8#-81.7#FL#120"),
    gkg_row("2", "https://news.example/fed", "Fed signals pause", orgs="Federal Reserve,5"),
    gkg_row("3", "https://news.example/bk", "Retailer files for bankruptcy", v2_themes="ECON_BANKRUPTCY,12"),
    gkg_row("4", "https://news.example/war", "Clashes continue", v2_themes="ARMEDCONFLICT,3"),   # risk theme alone
    gkg_row("5", "https://news.example/film", "Film runtime revealed", orgs="Google,3"),        # irrelevant
    gkg_row("6", "https://news.example/mkt", "Stocks wobble", v2_themes="ECON_STOCKMARKET,1"),  # one weak theme
    gkg_row("7", "https://news.example/mkt2", "Stocks fall on bankruptcy fears",
            v2_themes="ECON_STOCKMARKET,1;ECON_BANKRUPTCY,9"),                                  # strong theme
]


def test_gdelt_parse_keeps_relevant_rows_only():
    source = GdeltSource(fake_http(lambda r: httpx.Response(500)), GDELT_CFG, NameMatcher(COMPANIES))
    docs = source.parse_file(gkg_zip(*ROWS))
    assert [d.external_id for d in docs] == ["1", "2", "3", "7"]
    jpm = docs[0]
    assert jpm.payload["matched_tickers"] == ["JPM"]
    assert jpm.payload["locations"][0]["adm1"] == "USFL"
    assert jpm.payload["tone"] == pytest.approx(-4.2)
    assert jpm.published_at == datetime(2026, 10, 2, 2, 0, tzinfo=UTC)
    assert docs[1].payload["macro_orgs"] == ["Federal Reserve"]


def test_gdelt_boilerplate_orgs_need_a_headline_mention():
    from tripwire.universe import Company

    google = Company(ticker="GOOGL", sector="Communication Services", aliases=("Google", "Alphabet"))
    cfg = {**GDELT_CFG, "boilerplate_orgs": ["Google"]}
    source = GdeltSource(fake_http(lambda r: httpx.Response(500)), cfg, NameMatcher([google]))
    rows = [
        gkg_row("a", "https://x.example/roads", "Ontario highways add new speed limits", orgs="Google,3"),
        gkg_row("b", "https://x.example/eu", "Google fined by EU regulators", orgs="Google,0"),
    ]
    docs = source.parse_file(gkg_zip(*rows))
    assert [d.external_id for d in docs] == ["b"] and docs[0].payload["matched_tickers"] == ["GOOGL"]


def test_gdelt_fetch_follows_cursor_and_skips_missing_files():
    lastupdate = "1 a http://data.gdeltproject.org/gdeltv2/20261002020000.gkg.csv.zip\n"
    requested = []

    def handler(request):
        url = str(request.url)
        requested.append(url.rsplit("/", 1)[1])
        if url.endswith("lastupdate.txt"):
            return httpx.Response(200, text=lastupdate)
        if "20261002014500" in url:
            return httpx.Response(404)
        return httpx.Response(200, content=gkg_zip(ROWS[1]))

    source = GdeltSource(fake_http(handler), GDELT_CFG, NameMatcher(COMPANIES))
    result = source.fetch("20261002013000")
    assert requested[1:] == ["20261002014500.gkg.csv.zip", "20261002020000.gkg.csv.zip"]
    assert result.cursor == "20261002020000" and len(result.documents) == 1
    assert parse_lastupdate(lastupdate) == datetime(2026, 10, 2, 2, 0, tzinfo=UTC)


# ---------------------------------------------------------------- Finnhub
def test_finnhub_cursor_filters_seen_items_and_uses_header_auth():
    def handler(request):
        assert request.headers["X-Finnhub-Token"] == "secret-token-123456"
        assert "secret-token" not in str(request.url)
        if request.url.path.endswith("company-news"):
            assert request.url.params["symbol"] in {"JPM", "BRK.B"}
            return httpx.Response(200, json=[
                {"id": 11, "datetime": 1790000000, "headline": "Old JPM story", "summary": "", "url": "https://n/1",
                 "source": "Reuters", "related": "JPM", "category": "company"},
                {"id": 12, "datetime": 1790003600, "headline": "New JPM story", "summary": "Details.",
                 "url": "https://n/2", "source": "Reuters", "related": "JPM", "category": "company"},
            ])
        return httpx.Response(200, json=[{"id": 500, "datetime": 1790003000, "headline": "Markets rally",
                                          "url": "https://n/g", "source": "CNBC", "category": "general"}])

    source = FinnhubSource(fake_http(handler), "secret-token-123456", ["JPM", "BRK-B"], {"lookback_days": 2},
                           today=lambda: date(2026, 10, 2))
    cursor = json.dumps({"last": {"JPM": 1790000000, "BRK-B": 1790003600}, "general_min_id": 400})
    result = source.fetch(cursor)
    assert [d.title for d in result.documents] == ["New JPM story", "Markets rally"]
    state = json.loads(result.cursor)
    assert state["last"]["JPM"] == 1790003600 and state["general_min_id"] == 500
    assert result.documents[0].payload["related"] == ["JPM"]


# ---------------------------------------------------------------- EDGAR
SUBMISSIONS = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000019617-26-000300", "0000019617-26-000200", "0000019617-26-000100"],
            "form": ["8-K", "10-Q", "8-K"],
            "acceptanceDateTime": ["2026-10-01T20:15:21.000Z", "2026-09-30T10:00:00.000Z", "2026-09-01T12:00:00.000Z"],
            "items": ["2.04,9.01", "", "7.01"],
            "primaryDocument": ["jpm-8k.htm", "jpm-10q.htm", "old.htm"],
            "reportDate": ["2026-10-01", "2026-09-30", "2026-09-01"],
        }
    }
}


def test_edgar_emits_new_8k_with_exact_acceptance_time_and_items():
    http = fake_http(lambda r: httpx.Response(200, json=SUBMISSIONS))
    items = {"2.04": "Triggering Events That Accelerate a Direct Financial Obligation", "7.01": "Regulation FD"}
    source = EdgarSource(http, COMPANIES[:1], items, {"forms": ["8-K"]})
    result = source.fetch(json.dumps({"19617": "2026-09-15T00:00:00+00:00"}))
    [doc] = result.documents
    assert doc.published_at == datetime(2026, 10, 1, 20, 15, 21, tzinfo=UTC)
    assert doc.payload["items"] == ["2.04", "9.01"] and doc.payload["ticker"] == "JPM"
    assert doc.title.startswith("JPMORGAN CHASE & CO files 8-K: Item 2.04 Triggering")
    assert doc.url.endswith("/19617/000001961726000300/jpm-8k.htm")
    assert json.loads(result.cursor)["19617"].startswith("2026-10-01T20:15:21")
    assert source.fetch(result.cursor).documents == []  # nothing new on the next poll


def test_filing_title_drops_exhibit_item_unless_alone():
    assert filing_title("X", "8-K", ["9.01"], {"9.01": "Exhibits"}) == "X files 8-K: Item 9.01 Exhibits"


# ---------------------------------------------------------------- RSS
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>RBI</title>
<item><title>RBI announces repo rate decision</title><link>https://rbi.org.in/pr/1</link>
<description>&lt;p&gt;Policy repo rate unchanged.&lt;/p&gt;</description>
<pubDate>Thu, 01 Oct 2026 19:20:00</pubDate></item>
<item><title>Older release</title><link>https://rbi.org.in/pr/0</link>
<pubDate>Mon, 28 Sep 2026 10:00:00</pubDate></item>
</channel></rss>"""


def test_rss_treats_naive_dates_as_feed_timezone():
    http = fake_http(lambda r: httpx.Response(200, content=RSS.encode()))
    source = RssSource(http, {"name": "rbi", "url": "https://www.rbi.org.in/x.xml", "utc_offset_minutes": 330})
    result = source.fetch("2026-09-30T00:00:00+00:00")
    [doc] = result.documents
    assert doc.published_at == datetime(2026, 10, 1, 13, 50, tzinfo=UTC)  # 19:20 IST
    assert doc.source == "rbi" and doc.source_type == "regulator"
    assert parse_feed_date("Wed, 30 Sep 2026 13:00:00 GMT", 0) == datetime(2026, 9, 30, 13, tzinfo=UTC)


# ---------------------------------------------------------------- Bluesky
def test_bluesky_filter_and_pseudonymisation():
    f = PostFilter(NameMatcher(COMPANIES), ["earnings", "downgrade"], ["en"])
    assert f.match({"text": "Loading up on $JPM before earnings", "langs": ["en"]}) == {"JPM"}
    assert f.match({"text": "JPMorgan downgrade hits shares", "langs": ["en"]}) == {"JPM"}
    assert f.match({"text": "Lunch at JPMorgan HQ today", "langs": ["en"]}) == set()   # alias without finance word
    assert f.match({"text": "$JPM earnings", "langs": ["pt"]}) == set()                 # language filter
    event = {"did": "did:plc:abc123", "time_us": 1790000000000000, "kind": "commit",
             "commit": {"operation": "create", "collection": "app.bsky.feed.post", "rkey": "3k",
                        "record": {"text": "$JPM earnings beat", "langs": ["en"], "createdAt": "2026-10-02T00:00:00Z"}}}
    doc = post_to_document(event, {"JPM"})
    assert "did:plc" not in doc.model_dump_json()
    assert doc.url is None and len(doc.payload["author"]) == 16
    assert doc.published_at == datetime.fromtimestamp(1790000000, UTC)
