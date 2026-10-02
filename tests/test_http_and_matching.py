import httpx
import pytest

from helpers import COMPANIES, fake_http
from tripwire.ingestion.http import HttpError, TokenBucket
from tripwire.ingestion.matching import NameMatcher


def test_retries_on_429_honouring_retry_after_then_succeeds():
    calls, sleeps = [], []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    http = fake_http(handler, sleeps)
    assert http.get("https://finnhub.io/api/v1/x").json() == {"ok": True}
    assert len(calls) == 2 and sleeps == [7.0]


def test_gives_up_after_max_retries_on_5xx():
    http = fake_http(lambda r: httpx.Response(503))
    with pytest.raises(HttpError) as err:
        http.get("https://data.sec.gov/x")
    assert err.value.status == 503


def test_404_is_not_retried():
    calls = []
    http = fake_http(lambda r: calls.append(r) or httpx.Response(404))
    with pytest.raises(HttpError) as err:
        http.get("https://data.gdeltproject.org/x")
    assert err.value.status == 404 and len(calls) == 1


def test_secret_header_is_sent_but_not_in_url():
    seen = {}

    def handler(request):
        seen["url"], seen["token"] = str(request.url), request.headers.get("X-Finnhub-Token")
        return httpx.Response(200, json=[])

    fake_http(handler).get("https://finnhub.io/api/v1/news", headers={"X-Finnhub-Token": "k" * 20})
    assert seen["token"] == "k" * 20 and "k" * 20 not in seen["url"]


def test_token_bucket_waits_when_empty():
    t = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        t[0] += seconds

    bucket = TokenBucket(rate_per_second=2, burst=1, clock=lambda: t[0], sleep=sleep)
    bucket.acquire()
    bucket.acquire()
    assert sleeps == [pytest.approx(0.5)]


def test_matcher_rules():
    m = NameMatcher(COMPANIES)
    assert m.find("JPMorgan Chase posts record profit") == {"JPM"}
    assert m.find("jpmorgan cuts jobs") == {"JPM"}                 # mixed-case alias: case-insensitive
    assert m.find("UPS raises guidance") == {"UPS"}
    assert m.find("markets had ups and downs") == set()            # all-caps alias: case-sensitive
    assert m.find("AT&T outage hits millions") == {"T"}
    assert m.cashtags("Buying $JPM and $BRK.B, selling $XYZ") == {"JPM", "BRK-B"}
    assert m.org_lookup("Jpmorgan Chase") == "JPM"
    assert m.org_lookup("Google") is None


def test_force_ipv4_option(monkeypatch):
    from tripwire.ingestion.http import HttpClient
    from tripwire.ingestion.sources.bluesky import BlueskySource
    from tripwire.settings import Settings

    monkeypatch.setenv("TRIPWIRE_FORCE_IPV4", "true")
    assert Settings().force_ipv4 is True
    client = HttpClient("ua", force_ipv4=True)
    assert isinstance(client._client._transport, httpx.HTTPTransport)
    source = BlueskySource({"endpoint": "wss://x"}, post_filter=None, force_ipv4=True)
    assert source.connect_kwargs == {"family": __import__("socket").AF_INET}


def test_prefer_ipv4_restricts_name_resolution(monkeypatch):
    import socket

    from tripwire import netfix

    seen = []
    monkeypatch.setattr(netfix, "_original_getaddrinfo", lambda *args: seen.append(args) or [])
    monkeypatch.setattr(netfix, "_applied", False)
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)  # restored after the test
    netfix.prefer_ipv4()
    socket.getaddrinfo("example.com", 443)
    socket.getaddrinfo("example.com", 443, socket.AF_INET6)
    assert seen[0][2] == socket.AF_INET and seen[1][2] == socket.AF_INET6  # explicit family is respected
