from dataclasses import dataclass
from typing import Protocol

from tripwire.models import RawDocument, SourceType


@dataclass(frozen=True)
class FetchResult:
    documents: list[RawDocument]
    cursor: str | None  # checkpoint to resume from after a restart (stored per source)


class Source(Protocol):
    """A collector for one external feed (GDELT, Finnhub, EDGAR, Bluesky, RBI) or the replay files."""

    name: str
    source_type: SourceType

    def fetch(self, cursor: str | None) -> FetchResult: ...
