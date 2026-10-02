"""Stable identifiers used for idempotent ingestion.

The same article reached through two feeds (or re-fetched after a restart) must map to the same key,
so the store's UNIQUE constraint turns duplicates into no-ops.
"""

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|cmpid|ocid|ref|src)$", re.IGNORECASE)


def canonical_url(url: str) -> str:
    """Lower-case scheme and host, drop default ports, fragments and tracking parameters."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and not ((scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)):
        host = f"{host}:{parts.port}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, query, ""))


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def dedup_key(*, source: str, url: str | None, external_id: str | None, title: str, published_date: str) -> str:
    """Prefer the canonical URL (shared across feeds), then the source's own id, then title + date."""
    if url:
        basis = "url:" + canonical_url(url)
    elif external_id:
        basis = f"ext:{source}:{external_id}"
    else:
        basis = f"title:{normalize_title(title)}:{published_date}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
