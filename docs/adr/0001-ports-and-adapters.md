# ADR 0001: Ports and adapters

**Status:** accepted (2026-10-02)

**Context.** Judges must be able to run the project from the README on an ordinary laptop, while the design should still show production-grade components (a durable queue with retries and dead-lettering, a relational store).

**Decision.** The engine depends only on three interfaces in `src/tripwire/ports`: `Store`, `Queue` and `Source`. Adapters implement them:

| Port | Lite mode (default) | Full mode |
|---|---|---|
| Store | SQLite via SQLAlchemy | PostgreSQL via the same SQLAlchemy adapter |
| Queue | In-memory queue with Redis Streams semantics | Redis Streams (consumer groups, pending list, DLQ) |
| Source | Replay files in `data/replay` | Live collectors (GDELT, Finnhub, SEC EDGAR, Bluesky, RBI) |

**Consequences.** One codebase, two run modes chosen by settings. The in-memory queue must behave like Redis Streams (at-least-once delivery, redelivery after a visibility timeout, dead-letter after max attempts), which is enforced by tests. Consumers must be idempotent; the store's unique dedup key makes repeated inserts no-ops.
