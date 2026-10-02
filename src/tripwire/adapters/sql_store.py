"""Store adapter on SQLAlchemy Core. One implementation serves SQLite (lite) and PostgreSQL (full)."""

from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine, make_url

from tripwire.models import RawDocument

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


class SqlStore:
    def __init__(self, database_url: str) -> None:
        url = make_url(database_url)
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(database_url, future=True)

    def init(self) -> None:
        metadata.create_all(self.engine)

    def add_raw(self, doc: RawDocument) -> bool:
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
        dialect = self.engine.dialect.name
        if dialect == "sqlite":
            stmt = sqlite.insert(raw_documents).values(row).on_conflict_do_nothing(index_elements=["dedup_key"])
        elif dialect == "postgresql":
            stmt = postgresql.insert(raw_documents).values(row).on_conflict_do_nothing(
                index_elements=["dedup_key"]
            )
        else:
            raise NotImplementedError(f"unsupported database dialect: {dialect}")
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def count_raw(self, source: str | None = None) -> int:
        query = select(func.count()).select_from(raw_documents)
        if source:
            query = query.where(raw_documents.c.source == source)
        with self.engine.connect() as conn:
            return int(conn.execute(query).scalar_one())

    def health(self) -> dict[str, Any]:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"ok": True, "backend": self.engine.dialect.name, "raw_documents": self.count_raw()}
        except Exception as exc:  # health must report, never raise
            return {"ok": False, "backend": self.engine.dialect.name, "error": str(exc)}
