from datetime import UTC, datetime, timedelta, timezone

import pytest

from tripwire.ids import canonical_url, dedup_key, normalize_title


def test_canonical_url_drops_tracking_fragment_and_www():
    assert (
        canonical_url("HTTPS://WWW.Example.com/a/b/?utm_source=x&id=7&fbclid=y#top")
        == "https://example.com/a/b?id=7"
    )


def test_canonical_url_sorts_query_and_drops_default_port():
    assert canonical_url("http://example.com:80/p?b=2&a=1") == "http://example.com/p?a=1&b=2"


def test_same_url_from_two_feeds_gives_same_key_even_if_titles_differ():
    a = dedup_key(source="gdelt", url="https://example.com/x?utm_medium=rss", external_id=None,
                  title="Bank fails", published_date="2026-10-02")
    b = dedup_key(source="finnhub", url="https://www.example.com/x", external_id="991",
                  title="Bank FAILS!", published_date="2026-10-02")
    assert a == b


def test_fallbacks_without_url():
    by_ext = dedup_key(source="edgar", url=None, external_id="0001-26-000123", title="8-K", published_date="d")
    by_title = dedup_key(source="bluesky", url=None, external_id=None, title="Fed  hikes!", published_date="d")
    assert by_ext != by_title
    assert by_title == dedup_key(source="other", url=None, external_id=None, title="fed hikes", published_date="d")


def test_normalize_title():
    assert normalize_title("  Fed Hikes   Rates! ") == "fed hikes rates"


def test_raw_document_requires_timezone(make_doc):
    with pytest.raises(ValueError):
        make_doc(published_at=datetime(2026, 10, 2, 9, 0))


def test_raw_document_converts_to_utc(make_doc):
    ist = timezone(timedelta(hours=5, minutes=30))
    doc = make_doc(published_at=datetime(2026, 10, 2, 14, 44, tzinfo=ist))
    assert doc.published_at == datetime(2026, 10, 2, 9, 14, tzinfo=UTC)
