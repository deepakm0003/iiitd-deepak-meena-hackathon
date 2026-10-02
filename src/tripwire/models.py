"""Core data contracts shared by the ports and adapters."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from tripwire.ids import dedup_key

SourceType = Literal["news", "filing", "regulator", "social"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class RawDocument(BaseModel):
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

    @field_validator("published_at", "fetched_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @property
    def dedup_key(self) -> str:
        return dedup_key(
            source=self.source,
            url=self.url,
            external_id=self.external_id,
            title=self.title,
            published_date=self.published_at.date().isoformat(),
        )
