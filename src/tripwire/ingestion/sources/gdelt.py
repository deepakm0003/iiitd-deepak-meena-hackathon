"""GDELT 2.0 Global Knowledge Graph, read from the raw 15-minute files.

The DOC API is heavily rate-limited, so we download http://data.gdeltproject.org/gdeltv2/<ts>.gkg.csv.zip
directly. Each file is tab-separated with 27 columns (GKG 2.1). We keep records that mention a universe
company, a macro body (Fed, ECB, RBI...) or a market-relevant theme, and store organisations, themes, tone
and locations as hints for later stages (locations feed Module B's geography channel).
"""

import io
import logging
import re
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from tripwire.ingestion.http import HttpClient, HttpError
from tripwire.ingestion.matching import NameMatcher
from tripwire.models import RawDocument
from tripwire.ports.source import FetchResult

log = logging.getLogger(__name__)
STEP = timedelta(minutes=15)
TS_FORMAT = "%Y%m%d%H%M%S"

# GKG 2.1 column positions
C_RECORD_ID, C_DATE, C_SOURCE_NAME, C_URL = 0, 1, 3, 4
C_V1_THEMES, C_V2_THEMES, C_V1_LOCATIONS, C_V2_LOCATIONS = 7, 8, 9, 10
C_V2_ORGS, C_TONE, C_EXTRAS = 14, 15, 26
N_COLUMNS = 27

PAGE_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.DOTALL)


def parse_lastupdate(text: str) -> datetime:
    for line in text.strip().splitlines():
        url = line.split()[-1]
        if url.endswith(".gkg.csv.zip"):
            return datetime.strptime(url.rsplit("/", 1)[1][:14], TS_FORMAT).replace(tzinfo=UTC)
    raise ValueError("no GKG file listed in lastupdate.txt")


def _split_names(field: str) -> list[str]:
    """'Name,offset;Name2,offset' -> ['Name', 'Name2'] (order kept, duplicates removed)."""
    seen: dict[str, None] = {}
    for item in field.split(";"):
        if item:
            seen.setdefault(item.rsplit(",", 1)[0] if "," in item else item, None)
    return list(seen)


def parse_locations(v2_field: str, v1_field: str, limit: int = 10) -> list[dict[str, Any]]:
    """V2: type#name#country#adm1#adm2#lat#long#featureid#offset ; V1 lacks adm2 and offset."""
    out: dict[str, dict[str, Any]] = {}
    for item in (v2_field or v1_field).split(";"):
        parts = item.split("#")
        if len(parts) < 7:
            continue
        if v2_field:
            lat, lon = parts[5], parts[6]
        else:
            lat, lon = parts[4], parts[5]
        name = parts[1]
        if name and name not in out:
            out[name] = {
                "name": name,
                "country": parts[2],
                "adm1": parts[3],
                "lat": float(lat) if lat else None,
                "lon": float(lon) if lon else None,
            }
        if len(out) >= limit:
            break
    return list(out.values())


class GdeltSource:
    name = "gdelt"
    source_type = "news"

    def __init__(self, http: HttpClient, cfg: dict[str, Any], matcher: NameMatcher) -> None:
        self.http = http
        self.base_url = cfg["base_url"].rstrip("/")
        self.max_files = int(cfg.get("max_files_per_run", 8))
        self.matcher = matcher
        self.macro_orgs = {o.casefold() for o in cfg.get("macro_orgs", [])}
        self.finance_themes = set(cfg.get("finance_themes", []))
        self.risk_themes = set(cfg.get("risk_themes", []))
        self.boilerplate = {o.casefold() for o in cfg.get("boilerplate_orgs", [])}
        self.strong_themes = set(cfg.get("strong_themes", []))
        self.min_theme_hits = int(cfg.get("min_theme_hits", 1))

    def fetch(self, cursor: str | None) -> FetchResult:
        latest = parse_lastupdate(self.http.get(f"{self.base_url}/lastupdate.txt").text)
        ts = datetime.strptime(cursor, TS_FORMAT).replace(tzinfo=UTC) + STEP if cursor else latest
        if latest - ts > timedelta(days=1):  # very long outage: skip ahead instead of replaying a day of files
            log.warning("gdelt gap of %s; skipping ahead", latest - ts)
            ts = latest - STEP * (self.max_files - 1)
        documents: list[RawDocument] = []
        processed = None
        files = 0
        while ts <= latest and files < self.max_files:  # catch up at most max_files per run
            files += 1
            try:
                content = self.http.get(f"{self.base_url}/{ts:{TS_FORMAT}}.gkg.csv.zip").content
            except HttpError as exc:
                if exc.status != 404:  # GDELT occasionally skips a slot; anything else is a real failure
                    raise
            else:
                documents.extend(self.parse_file(content))
            processed = ts
            ts += STEP
        return FetchResult(documents, processed.strftime(TS_FORMAT) if processed else cursor)

    def parse_file(self, content: bytes) -> list[RawDocument]:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            text = archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")
        documents = []
        for line in text.splitlines():
            columns = line.split("\t")
            if len(columns) >= N_COLUMNS and (doc := self.parse_row(columns)):
                documents.append(doc)
        return documents

    def parse_row(self, cols: list[str]) -> RawDocument | None:
        orgs = _split_names(cols[C_V2_ORGS])
        themes = set(_split_names(cols[C_V2_THEMES])) | {t for t in cols[C_V1_THEMES].split(";") if t}
        title_match = PAGE_TITLE.search(cols[C_EXTRAS])
        in_title = self.matcher.find(title_match.group(1)) if title_match else set()
        tickers = sorted({
            t for o in orgs
            if (t := self.matcher.org_lookup(o)) and (o.casefold() not in self.boilerplate or t in in_title)
        })
        macro = sorted({o for o in orgs if o.casefold() in self.macro_orgs})
        finance = themes & self.finance_themes
        theme_ok = bool(finance & self.strong_themes) or len(finance) >= self.min_theme_hits
        if not (tickers or macro or theme_ok):
            return None
        if not title_match or not cols[C_URL].startswith("http"):
            return None
        tone = cols[C_TONE].split(",")[0]
        return RawDocument(
            source=self.name,
            source_type="news",
            title=title_match.group(1).strip(),
            url=cols[C_URL],
            external_id=cols[C_RECORD_ID],
            published_at=datetime.strptime(cols[C_DATE], TS_FORMAT).replace(tzinfo=UTC),
            payload={
                "source_name": cols[C_SOURCE_NAME],
                "matched_tickers": tickers,
                "macro_orgs": macro,
                "orgs": orgs[:30],
                "themes": sorted(finance | (themes & self.risk_themes)),
                "tone": float(tone) if tone else None,
                "locations": parse_locations(cols[C_V2_LOCATIONS], cols[C_V1_LOCATIONS]),
            },
        )
