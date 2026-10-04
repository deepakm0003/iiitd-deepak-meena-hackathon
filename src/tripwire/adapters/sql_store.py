"""Store adapter on SQLAlchemy Core. One implementation serves SQLite (lite) and PostgreSQL (full)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
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

from tripwire.models import Document, FilingText, PriceBar, RawDocument, RunStats

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

filing_texts = Table(
    "filing_texts",
    metadata,
    Column("accession", String(32), primary_key=True),
    Column("cik", Integer, nullable=False, index=True),
    Column("main_text", Text, nullable=False),
    Column("exhibit_name", String(256)),
    Column("exhibit_text", Text, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("status", String(8), nullable=False),
    Column("error", Text),
)

prices_daily = Table(
    "prices_daily",
    metadata,
    Column("ticker", String(32), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("close", Float),
    Column("adj_close", Float, nullable=False),
    Column("volume", Float),
    Column("source", String(16), nullable=False),
)


doc_annotations = Table(
    "doc_annotations",
    metadata,
    Column("raw_id", Integer, ForeignKey("raw_documents.id"), primary_key=True),
    Column("published_at", DateTime(timezone=True), nullable=False, index=True),
    Column("source", String(32), nullable=False),
    Column("primary_entity", String(16), nullable=False, index=True),
    Column("event_type", String(40), nullable=False, index=True),
    Column("event_method", String(40), nullable=False),
    Column("sentiment", Float, nullable=False),
    Column("annotation", JSON, nullable=False),
    Column("annotated_at", DateTime(timezone=True), nullable=False),
)


events = Table(
    "events",
    metadata,
    Column("event_id", String(32), primary_key=True),
    Column("key", String(16), nullable=False, index=True),
    Column("first_seen", DateTime(timezone=True), nullable=False, index=True),
    Column("last_seen", DateTime(timezone=True), nullable=False),
    Column("n_docs", Integer, nullable=False),
    Column("n_publishers", Integer, nullable=False),
    Column("novelty", Float, nullable=False),
    Column("corroboration", Float, nullable=False),
    Column("credibility", Float, nullable=False),
    Column("detail", JSON, nullable=False),  # sources, source types, publishers, doc ids
)

event_members = Table(
    "event_members",
    metadata,
    Column("raw_id", Integer, ForeignKey("raw_documents.id"), primary_key=True),
    Column("event_id", String(32), nullable=False, index=True),
    Column("similarity", Float, nullable=False),
    Column("novelty", Float, nullable=False),
)


signals = Table(
    "signals",
    metadata,
    Column("event_id", String(32), primary_key=True),
    Column("primary_entity", String(16), nullable=False, index=True),
    Column("event_type", String(40), nullable=False, index=True),
    Column("impact", Float, nullable=False, index=True),
    Column("sentiment", Float, nullable=False),
    Column("risk_level", String(12), nullable=False),
    Column("first_seen", DateTime(timezone=True), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)


stress_runs = Table(
    "stress_runs",
    metadata,
    Column("run_id", String(32), primary_key=True),
    Column("event_id", String(32), nullable=True, index=True),
    Column("trigger", String(12), nullable=False),  # auto | manual | what-if
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("event_type", String(40), nullable=False),
    Column("impact", Float, nullable=False),
    Column("pnl_total", Float, nullable=False),
    Column("cet1_ratio_after", Float, nullable=False),
    Column("result", JSON, nullable=False),
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

    def iter_documents(self, since: datetime | None = None, until: datetime | None = None) -> list[Document]:
        query = select(documents).order_by(documents.c.published_at)
        if since:
            query = query.where(documents.c.published_at >= since)
        if until:
            query = query.where(documents.c.published_at <= until)
        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            Document(**{**r._mapping, "published_at": _aware(r.published_at), "normalized_at": _aware(r.normalized_at)})
            for r in rows
        ]

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

    # ---- 8-K texts -------------------------------------------------------------------------------
    def add_filing_text(self, row: FilingText) -> None:
        values = row.model_dump()
        updates = {k: v for k, v in values.items() if k != "accession"}
        stmt = (
            self._insert(filing_texts)
            .values(values)
            .on_conflict_do_update(index_elements=["accession"], set_=updates)
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def get_filing_text(self, accession: str) -> FilingText | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(filing_texts).where(filing_texts.c.accession == accession)).first()
        return FilingText(**{**row._mapping, "fetched_at": _aware(row.fetched_at)}) if row else None

    def edgar_filings_missing_text(self, limit: int = 100_000) -> list[dict[str, Any]]:
        """EDGAR raw documents with no successfully fetched text yet: [{accession, cik, primary_document}]."""
        with self.engine.connect() as conn:
            done = {r[0] for r in conn.execute(select(filing_texts.c.accession).where(filing_texts.c.status == "ok"))}
            rows = conn.execute(
                select(raw_documents.c.external_id, raw_documents.c.payload)
                .where(raw_documents.c.source == "edgar")
                .order_by(raw_documents.c.published_at.desc())
            ).fetchall()
        out = []
        for accession, payload in rows:
            if accession and accession not in done and payload.get("cik"):
                out.append({"accession": accession, "cik": int(payload["cik"]),
                            "primary_document": payload.get("primary_document")})
        return out[:limit]

    # ---- NLP annotations -----------------------------------------------------------------------
    def add_annotations(self, annotations: list) -> int:
        """Upsert annotations (re-annotating with a newer model replaces the old row)."""
        if not annotations:
            return 0
        rows = [
            {
                "raw_id": a.raw_id,
                "published_at": a.published_at,
                "source": a.source,
                "primary_entity": a.primary,
                "event_type": a.event_type,
                "event_method": a.event_method,
                "sentiment": a.sentiment,
                "annotation": a.model_dump(mode="json"),
                "annotated_at": a.annotated_at,
            }
            for a in annotations
        ]
        with self.engine.begin() as conn:
            stmt = self._insert(doc_annotations).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["raw_id"],
                set_={c: stmt.excluded[c] for c in rows[0] if c != "raw_id"},
            )
            conn.execute(stmt)
        return len(rows)

    def documents_without_annotation(self, limit: int = 1000) -> list[Document]:
        query = (
            select(documents)
            .outerjoin(doc_annotations, doc_annotations.c.raw_id == documents.c.raw_id)
            .where(doc_annotations.c.raw_id.is_(None))
            .order_by(documents.c.published_at.desc())
            .limit(limit)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            Document(**{**r._mapping, "published_at": _aware(r.published_at), "normalized_at": _aware(r.normalized_at)})
            for r in rows
        ]

    def get_annotations(self, since: datetime | None = None, until: datetime | None = None,
                        primary: str | None = None) -> list[dict]:
        query = select(doc_annotations.c.annotation).order_by(doc_annotations.c.published_at)
        if primary:
            query = query.where(doc_annotations.c.primary_entity == primary)
        if since:
            query = query.where(doc_annotations.c.published_at >= since)
        if until:
            query = query.where(doc_annotations.c.published_at <= until)
        with self.engine.connect() as conn:
            return [row[0] for row in conn.execute(query)]

    def delete_annotations(self, source: str) -> int:
        with self.engine.begin() as conn:
            return conn.execute(doc_annotations.delete().where(doc_annotations.c.source == source)).rowcount

    def count_annotations(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(doc_annotations)).scalar_one())

    # ---- events (clusters) ---------------------------------------------------------------------
    def replace_events(self, event_rows: list[dict], member_rows: list[dict]) -> None:
        """Atomically replace all events: clustering is recomputed deterministically over the full history."""
        with self.engine.begin() as conn:
            conn.execute(event_members.delete())
            conn.execute(events.delete())
            for start in range(0, len(event_rows), 500):
                conn.execute(events.insert(), event_rows[start : start + 500])
            for start in range(0, len(member_rows), 1000):
                conn.execute(event_members.insert(), member_rows[start : start + 1000])

    def get_events(self, since: datetime | None = None) -> list[dict]:
        query = select(events).order_by(events.c.first_seen)
        if since:
            query = query.where(events.c.last_seen >= since)
        with self.engine.connect() as conn:
            return [
                {**r._mapping, "first_seen": _aware(r.first_seen), "last_seen": _aware(r.last_seen)}
                for r in conn.execute(query)
            ]

    def count_events(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(events)).scalar_one())

    # ---- signals (the Risk Engine's output) ----------------------------------------------------
    def upsert_signals(self, payloads: list[dict], prune: bool = False) -> int:
        """Insert or update; updated_at changes only when the signal's content changed (drives the stream).

        prune=True removes signals whose event no longer exists (events are recomputed every cycle: an item
        re-classified as NONE, or merged into another event, must not leave a stale signal behind).
        """
        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            if prune:
                keep = [p["event_id"] for p in payloads]
                conn.execute(signals.delete().where(signals.c.event_id.not_in(keep)) if keep else signals.delete())
            if not payloads:
                return 0
            existing = {r[0]: r[1] for r in conn.execute(select(signals.c.event_id, signals.c.payload))}
            changed = 0
            for p in payloads:
                p = json.loads(json.dumps(p, default=str))  # same normal form as what the database returns
                comparable = {k: v for k, v in p.items() if k != "scored_at"}
                old = existing.get(p["event_id"])
                if old is not None and {k: v for k, v in old.items() if k != "scored_at"} == comparable:
                    continue
                row = {"event_id": p["event_id"], "primary_entity": p["primary_entity"], "event_type": p["event_type"],
                       "impact": p["impact_score"], "sentiment": p["sentiment_score"], "risk_level": p["risk_level"],
                       "first_seen": datetime.fromisoformat(p["first_seen_at"]), "updated_at": now, "payload": p}
                stmt = self._insert(signals).values(row)
                conn.execute(stmt.on_conflict_do_update(index_elements=["event_id"],
                                                        set_={k: v for k, v in row.items() if k != "event_id"}))
                changed += 1
        return changed

    def query_signals(self, min_impact: float | None = None, event_type: str | None = None,
                      entity: str | None = None, since: datetime | None = None, updated_since: datetime | None = None,
                      limit: int = 100, exclude_other: bool = False) -> list[dict]:
        query = select(signals.c.payload).order_by(signals.c.first_seen.desc()).limit(limit)
        if exclude_other:
            query = query.where(signals.c.event_type != "Other")
        if min_impact is not None:
            query = query.where(signals.c.impact >= min_impact)
        if event_type:
            query = query.where(signals.c.event_type == event_type)
        if entity:
            query = query.where(signals.c.primary_entity == entity)
        if since:
            query = query.where(signals.c.first_seen >= since)
        if updated_since:
            query = query.where(signals.c.updated_at > updated_since)
        with self.engine.connect() as conn:
            return [r[0] for r in conn.execute(query)]

    def signal_rows(self, since: datetime) -> list[dict]:
        cols = (signals.c.event_id, signals.c.event_type, signals.c.risk_level, signals.c.impact, signals.c.first_seen)
        with self.engine.connect() as conn:
            rows = conn.execute(select(*cols).where(signals.c.first_seen >= since))
            return [{"event_id": r[0], "event_type": r[1], "risk_level": r[2], "impact": r[3], "first_seen": r[4]}
                    for r in rows]

    def get_signal(self, event_id: str) -> dict | None:
        with self.engine.connect() as conn:
            return conn.execute(select(signals.c.payload).where(signals.c.event_id == event_id)).scalar_one_or_none()

    def count_signals(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(signals)).scalar_one())

    # ---- stress runs (Module B) ------------------------------------------------------------------
    def add_stress_run(self, run: dict) -> None:
        run = json.loads(json.dumps(run, default=str))
        row = {"run_id": run["run_id"], "event_id": run.get("event_id"), "trigger": run["trigger"],
               "created_at": datetime.fromisoformat(run["created_at"]), "event_type": run["scenario"]["event_type"],
               "impact": run["scenario"]["impact"], "pnl_total": run["pnl_total"],
               "cet1_ratio_after": run["capital"]["cet1_ratio_after"], "result": run}
        with self.engine.begin() as conn:
            conn.execute(self._insert(stress_runs).values(row).on_conflict_do_nothing(index_elements=["run_id"]))

    def get_stress_run(self, run_id: str) -> dict | None:
        with self.engine.connect() as conn:
            return conn.execute(select(stress_runs.c.result).where(stress_runs.c.run_id == run_id)).scalar_one_or_none()

    def list_stress_runs(self, limit: int = 50, event_id: str | None = None) -> list[dict]:
        """Run summaries, newest first (the full result, with every position's paths, is in get_stress_run)."""
        query = select(stress_runs).order_by(stress_runs.c.created_at.desc()).limit(limit)
        if event_id:
            query = query.where(stress_runs.c.event_id == event_id)
        with self.engine.connect() as conn:
            return [
                {"run_id": r.run_id, "event_id": r.event_id, "trigger": r.trigger,
                 "created_at": _aware(r.created_at).isoformat(), "event_type": r.event_type, "impact": r.impact,
                 "pnl_total": r.pnl_total, "cet1_ratio_after": r.cet1_ratio_after,
                 "scenario_name": r.result["scenario"]["name"]}
                for r in conn.execute(query)
            ]

    # ---- prices --------------------------------------------------------------------------------
    def upsert_prices(self, bars: list[PriceBar]) -> int:
        if not bars:
            return 0
        rows = [b.model_dump() for b in bars]
        with self.engine.begin() as conn:
            for start in range(0, len(rows), 500):
                stmt = self._insert(prices_daily).values(rows[start : start + 500])
                stmt = stmt.on_conflict_do_update(
                    index_elements=["ticker", "date"],
                    set_={c: stmt.excluded[c] for c in ("close", "adj_close", "volume", "source")},
                )
                conn.execute(stmt)
        return len(rows)

    def get_prices(self, ticker: str) -> list[PriceBar]:
        query = select(prices_daily).where(prices_daily.c.ticker == ticker).order_by(prices_daily.c.date)
        with self.engine.connect() as conn:
            return [PriceBar(**r._mapping) for r in conn.execute(query)]

    def price_coverage(self) -> dict[str, tuple[str, str, int]]:
        query = select(
            prices_daily.c.ticker, func.min(prices_daily.c.date), func.max(prices_daily.c.date), func.count()
        ).group_by(prices_daily.c.ticker)
        with self.engine.connect() as conn:
            return {t: (str(a), str(b), int(n)) for t, a, b, n in conn.execute(query)}

    def health(self) -> dict[str, Any]:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {
                "ok": True,
                "backend": self.engine.dialect.name,
                "raw_documents": self.count_raw(),
                "documents": self.count_documents(),
                "annotated": self.count_annotations(),
                "events": self.count_events(),
                "signals": self.count_signals(),
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
