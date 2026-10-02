from collections.abc import Iterator
from typing import Any, Protocol

from tripwire.models import Document, RawDocument, RunStats


class Store(Protocol):
    """Persistent storage. Lite mode: SQLite. Full mode: PostgreSQL. Same adapter via SQLAlchemy."""

    def init(self) -> None:
        """Create tables if they do not exist."""

    # Raw capture (immutable, deduplicated)
    def add_raw(self, doc: RawDocument) -> int | None:
        """Insert a raw document. Returns its id, or None (and changes nothing) if it is a duplicate."""

    def get_raw(self, raw_id: int) -> RawDocument | None: ...

    def iter_raw(self, source: str | None = None, limit: int | None = None) -> Iterator[RawDocument]:
        """Newest first."""

    def count_raw(self, source: str | None = None) -> int: ...

    # Normalised documents
    def add_document(self, doc: Document) -> bool:
        """Insert once per raw_id; returns False if it already exists."""

    def raw_ids_without_document(self, limit: int = 100_000) -> list[int]:
        """Raw documents stored but not yet normalised (recovery after a crash)."""

    def count_documents(self) -> int: ...

    # Ingestion bookkeeping
    def get_checkpoint(self, source: str) -> str | None: ...

    def set_checkpoint(self, source: str, cursor: str | None) -> None: ...

    def add_quarantine(self, source: str, reason: str, payload: dict[str, Any], raw_id: int | None = None) -> None: ...

    def count_quarantine(self) -> int: ...

    def record_run(self, stats: RunStats) -> None: ...

    def recent_runs(self, limit: int = 20) -> list[RunStats]: ...

    def health(self) -> dict[str, Any]: ...
