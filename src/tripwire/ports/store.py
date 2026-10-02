from typing import Any, Protocol

from tripwire.models import RawDocument


class Store(Protocol):
    """Persistent storage. Lite mode: SQLite. Full mode: PostgreSQL. Same adapter via SQLAlchemy."""

    def init(self) -> None:
        """Create tables if they do not exist."""

    def add_raw(self, doc: RawDocument) -> bool:
        """Insert a raw document. Returns False (and changes nothing) if it is a duplicate."""

    def count_raw(self, source: str | None = None) -> int: ...

    def health(self) -> dict[str, Any]: ...
