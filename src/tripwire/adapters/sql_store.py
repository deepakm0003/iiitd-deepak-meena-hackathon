"""Store adapter on SQLAlchemy Core. One implementation serves SQLite (lite) and PostgreSQL (full)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    select,
    text,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine, make_url

from tripwire.models import Document, RawDocument, RunStats

metadata = MetaData()

raw_documents = Table(
    "raw_documents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dedup_key", String(64), nullable=False, unique=True),
    Column("source", String(32), nullable=False, index=True),
    Column("source_type", String(16), nullable=False),
    Column("url", Text),
    Column("external_id", String(256)),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False, default=""),
    Column("published_at", DateTime(timezone=True), nullable=False, index=True),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
)

documents = Table(
    "documents",
    metadata,
    Column("raw_id", Integer, ForeignKey("raw_documents.id"), primary_key=True),
    Column("dedup_key", String(64), nullable=False),
    Column("source", String(32), nullable=False),
    Column("source_type", String(16), nullable=False),
    Column("title", Text, nullable=False),
    Column("lead", Text, nullable=False, default=""),
    Column("lang", String(8), nullable=False),
    Column("url", Text),
    Column("published_at", DateTime(timezone=True), nullable=False, index=True),
    Column("normalized_at", DateTime(timezone=True), nullable=False),
    Column("hints", JSON, nullable=False, default=dict),
)

ingestion_checkpoints = Table(
    "ingestion_checkpoints",
    metadata,
    Column("source", String(32), primary_key=True),
    Column("cursor", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

quarantine = Table(
    "quarantine",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(32), nullable=False),
    Column("raw_id", Integer, index=True),
    Column("reason", Text, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

source_runs = Table(
    "source_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(32), nullable=False, index=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("fetched", Integer, nullable=False),
    Column("inserted", Integer, nullable=False),
    Column("duplicates", Integer, nullable=False),
    Column("status", String(8), nullable=False),
    Column("error", Text),
)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; values are always stored as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class SqlStore:
    def __init__(self, database_url: str) -> None:
        url = make_url(database_url)
        self._sqlite = url.get_backend_name() == "sqlite"
        if self._sqlite and url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"timeout": 30, "check_same_thread": False} if self._sqlite else {}
        self.engine: Engine = create_engine(database_url, connect_args=connect_args)
        if self._sqlite:
            event.listen(self.engine, "connect", _sqlite_pragmas)

    def init(self) -> None:
        metadata.create_all(self.engine)

    def _insert(self, table: Table):
        return (sqlite if self._sqlite else postgresql).insert(table)

    # ---- raw documents -------------------------------------------------------------------------
    def add_raw(self, doc: RawDocument) -> int | None:
        row = {
            "dedup_key": doc.dedup_key,
            "source": doc.source,
            "source_type": doc.source_type,
            "url": doc.url,
            "external_id": doc.external_id,
            "title": doc.title,
            "text": doc.text,
            "published_at": doc.published_at,
            "fetched_at": doc.fetched_at,
            "payload": doc.payload,
        }
        stmt = (
            self._insert(raw_documents)
            .values(row)
            .on_conflict_do_nothing(index_elements=["dedup_key"])
            .returning(raw_documents.c.id)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).scalar_one_or_none()

    def _raw_from_row(self, row) -> RawDocument:
        return RawDocument(
            source=row.source,
            source_type=row.source_type,
            title=row.title,
            text=row.text,
            url=row.url,
            external_id=row.external_id,
            published_at=_aware(row.published_at),
            fetched_at=_aware(row.fetched_at),
            payload=row.payload or {},
        )

    def get_raw(self, raw_id: int) -> RawDocument | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(raw_documents).where(raw_documents.c.id == raw_id)).first()
        return self._raw_from_row(row) if row else None

    def iter_raw(self, source: str | None = None, limit: int | None = None) -> Iterator[RawDocument]:
        query = select(raw_documents).order_by(raw_documents.c.published_at.desc())
        if source:
            query = query.where(raw_documents.c.source == source)
        if limit:
            query = query.limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        for row in rows:
            yield self._raw_from_row(row)

    def count_raw(self, source: str | None = None) -> int:
        query = select(func.count()).select_from(raw_documents)
        if source:
            query = query.where(raw_documents.c.source == source)
        with self.engine.connect() as conn:
            return int(conn.execute(query).scalar_one())

    # ---- normalised documents ------------------------------------------------------------------
    def add_document(self, doc: Document) -> bool:
        stmt = (
            self._insert(documents)
            .values(doc.model_dump())
            .on_conflict_do_nothing(index_elements=["raw_id"])
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def raw_ids_without_document(self, limit: int = 100_000) -> list[int]:
        query = (
            select(raw_documents.c.id)
            .outerjoin(documents, documents.c.raw_id == raw_documents.c.id)
            .where(documents.c.raw_id.is_(None))
            .where(raw_documents.c.id.not_in(select(quarantine.c.raw_id).where(quarantine.c.raw_id.is_not(None))))
            .order_by(raw_documents.c.id)
            .limit(limit)
        )
        with self.engine.connect() as conn:
            return [row[0] for row in conn.execute(query)]

    def count_documents(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(documents)).scalar_one())

    # ---- ingestion bookkeeping -----------------------------------------------------------------
    def get_checkpoint(self, source: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                select(ingestion_checkpoints.c.cursor).where(ingestion_checkpoints.c.source == source)
            ).scalar_one_or_none()

    def set_checkpoint(self, source: str, cursor: str | None) -> None:
        now = datetime.now(UTC)
        stmt = (
            self._insert(ingestion_checkpoints)
            .values(source=source, cursor=cursor, updated_at=now)
            .on_conflict_do_update(index_elements=["source"], set_={"cursor": cursor, "updated_at": now})
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def add_quarantine(self, source: str, reason: str, payload: dict[str, Any], raw_id: int | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                quarantine.insert().values(
                    source=source, raw_id=raw_id, reason=reason, payload=payload, created_at=datetime.now(UTC)
                )
            )

    def count_quarantine(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(quarantine)).scalar_one())

    def record_run(self, stats: RunStats) -> None:
        with self.engine.begin() as conn:
            conn.execute(source_runs.insert().values(stats.model_dump()))

    def recent_runs(self, limit: int = 20) -> list[RunStats]:
        query = select(source_runs).order_by(source_runs.c.id.desc()).limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            RunStats(
                source=r.source,
                started_at=_aware(r.started_at),
                finished_at=_aware(r.finished_at),
                fetched=r.fetched,
                inserted=r.inserted,
                duplicates=r.duplicates,
                status=r.status,
                error=r.error,
            )
            for r in rows
        ]

    def health(self) -> dict[str, Any]:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {
                "ok": True,
                "backend": self.engine.dialect.name,
                "raw_documents": self.count_raw(),
                "documents": self.count_documents(),
                "quarantined": self.count_quarantine(),
            }
        except Exception as exc:  # health must report, never raise
            return {"ok": False, "backend": self.engine.dialect.name, "error": str(exc)}


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    # WAL lets collectors (writers) and the API/dashboard (readers) work at the same time.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
