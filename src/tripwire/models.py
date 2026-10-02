"""Core data contracts shared by the ports and adapters."""

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from tripwire.ids import dedup_key

SourceType = Literal["news", "filing", "regulator", "social"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class _UtcModel(BaseModel):
    @field_validator("published_at", "fetched_at", "normalized_at", check_fields=False)
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class RawDocument(_UtcModel):
    """One item exactly as a collector received it (provenance: OBSERVED)."""

    source: str
    source_type: SourceType
    title: str
    text: str = ""
    url: str | None = None
    external_id: str | None = None
    published_at: datetime
    fetched_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return dedup_key(
            source=self.source,
            url=self.url,
            external_id=self.external_id,
            title=self.title,
            published_date=self.published_at.date().isoformat(),
        )


class Document(_UtcModel):
    """A cleaned document ready for NLP. Text is still OBSERVED; only formatting was normalised."""

    raw_id: int
    dedup_key: str
    source: str
    source_type: SourceType
    title: str
    lead: str = ""
    lang: str = "en"
    url: str | None = None
    published_at: datetime
    normalized_at: datetime = Field(default_factory=utc_now)
    # Source-provided hints for entity linking (e.g. Finnhub 'related', EDGAR ticker/CIK, GDELT organisations).
    hints: dict[str, Any] = Field(default_factory=dict)


class FilingText(BaseModel):
    """Verbatim text of an 8-K: main document plus the press-release exhibit when present (OBSERVED)."""

    accession: str
    cik: int
    main_text: str = ""
    exhibit_name: str | None = None
    exhibit_text: str = ""
    fetched_at: datetime
    status: Literal["ok", "error"] = "ok"
    error: str | None = None


class PriceBar(BaseModel):
    """One daily observation. Tickers like 'FRED:DGS10' hold FRED series (value in adj_close)."""

    ticker: str
    date: date
    close: float | None = None
    adj_close: float
    volume: float | None = None
    source: str


class RunStats(BaseModel):
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
