"""FastAPI app: the Risk Engine's output, for Module B and the dashboard (OpenAPI docs at /docs).

  GET  /health                       store and pipeline health
  GET  /signals                      list, filters: min_impact, event_type, entity, since, exclude_other, limit
  GET  /signals/stats                counts per day, event type and risk level over the last N days (dashboard)
  GET  /signals/{event_id}           one signal with breakdown, evidence and documents
  GET  /companies/{ticker}/risk      rolling 7-day view for one company
  GET  /ops/status                   collector status (per-source last run, failures, pauses)
  GET  /model/metrics                validation numbers as last measured (docs/results), for the website
Analyse (uploads are processed in memory with the production models and never stored):
  GET  /analyze/status               whether the models are loaded
  POST /analyze/text                 one article or press release: full trace, Impact, trigger, stress run
  POST /analyze/batch                up to 300 headlines/texts: one row of scores each
  POST /analyze/portfolio            your own positions (CSV rows) against this week's live signals
  WS   /stream/signals               pushes new or changed signals (checks every 5 s), heartbeat every 15 s
Module B (stress testing the synthetic wholesale book):
  GET  /portfolio                    book summary: exposures by type, sector, grade, state; capital
  GET  /watchlist                    early-warning list, Green / Amber / Red, with the evidence per name
  GET  /signals/{event_id}/stress-decision   would this signal launch a stress test, and why (every check)
  GET  /signals/{event_id}/trace     signal -> evidence -> impact -> exposure -> shocks -> P&L -> ECL -> CET1
  POST /stress-test                  run for an event ({"event_id": ...}) or a what-if scenario
  GET  /stress-test/{run_id}         one run: P&L by position with causal paths, stages, CET1, reverse stress
  GET  /stress-runs                  run summaries, newest first (automatic, manual and what-if)
"""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from tripwire.config import load_yaml
from tripwire.factory import build_store
from tripwire.settings import get_settings

EVENT_TYPES = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]


class AnalyzeRequest(BaseModel):
    title: str = Field("", max_length=1000)
    text: str = Field("", max_length=100_000, description="article body; the classifier reads the opening")
    source_type: Literal["news", "filing", "regulator", "social"] = "news"
    url: str | None = Field(None, max_length=2000, description="recorded with the result, never fetched")


class BatchItem(BaseModel):
    title: str = Field("", max_length=1000)
    text: str = Field("", max_length=5000)


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(..., min_length=1, max_length=300)
    source_type: Literal["news", "filing", "regulator", "social"] = "news"


class PortfolioRequest(BaseModel):
    rows: list[dict[str, str | float | int | None]] = Field(..., min_length=1, max_length=500,
                                                            description="one position per row; see portfolio/upload.py")


class StressRequest(BaseModel):
    """Either an event_id (run that event's scenario) or a what-if: event_type + impact (+ optional target)."""

    event_id: str | None = None
    event_type: str | None = None
    impact: float | None = Field(None, ge=1, le=10)
    entity: str | None = Field(None, description="ticker of the company the event hits")
    sector: str | None = None
    states: list[str] = Field(default_factory=list, description="US state codes, for the geography channel")
    hard_flags: list[str] = Field(default_factory=list, description="e.g. 1.03 (bankruptcy)")


def create_app(store=None, stress=None, analyzer_preload: bool | None = None) -> FastAPI:
    settings = get_settings()
    def now() -> datetime:
        return settings.as_of or datetime.now(UTC)

    preload = analyzer_preload if analyzer_preload is not None else store is None  # the server, not tests
    store = store or build_store(settings)
    if stress is None:
        from tripwire.stress.service import load_service

        stress = load_service(store, settings.data_dir)

    def service():
        if stress is None:
            raise HTTPException(503, "the book is not built: run `python -m tripwire book` and `market-inputs`")
        return stress
    from tripwire.analyze import Analyzer

    analyzer = Analyzer(store, stress, settings.data_dir.parent, clock=now)
    if preload:  # load the models in the background so the first upload does not wait for them
        threading.Thread(target=analyzer.warm, daemon=True).start()
    tickers = {c["ticker"] for c in load_yaml("universe.yaml").get("companies", [])}
    app = FastAPI(title="Tripwire Risk Engine API", version="1.0",
                  description="Structured, explainable financial risk signals from news, filings and social posts.")

    @app.get("/health")
    def health():
        return {"status": "ok", "store": store.health(), "time": now().isoformat(),
                "as_of": settings.as_of.isoformat() if settings.as_of else None}

    @app.get("/signals")
    def list_signals(
        min_impact: float | None = Query(None, ge=1, le=10),
        event_type: str | None = None,
        entity: str | None = Query(None, description="ticker, MACRO"),
        since: datetime | None = None,
        limit: int = Query(100, ge=1, le=1000),
        exclude_other: bool = Query(False, description="drop items classified Other (no risk event)"),
    ):
        if event_type and event_type not in EVENT_TYPES:
            raise HTTPException(422, f"unknown event_type; choose from {EVENT_TYPES}")
        return store.query_signals(min_impact=min_impact, event_type=event_type,
                                   entity=entity.upper() if entity else None, since=since, limit=limit,
                                   exclude_other=exclude_other)

    @app.get("/signals/stats")
    def signal_stats(days: int = Query(7, ge=1, le=90)):
        rows = store.signal_rows(now() - timedelta(days=days))
        by_day: dict[str, dict[str, int]] = {}
        for r in rows:
            day = by_day.setdefault(r["first_seen"].date().isoformat(), {})
            day[r["event_type"]] = day.get(r["event_type"], 0) + 1
        return {
            "days": days,
            "total": len(rows),
            "by_type": _count(r["event_type"] for r in rows),
            "by_risk": _count(r["risk_level"] for r in rows),
            "by_day": [{"date": d, "total": sum(c.values()), "by_type": c} for d, c in sorted(by_day.items())],
        }

    @app.get("/signals/{event_id}")
    def get_signal(event_id: str):
        signal = store.get_signal(event_id)
        if signal is None:
            raise HTTPException(404, "unknown event_id")
        return signal

    @app.get("/model/metrics")
    def model_metrics():
        """Validation numbers as last measured (docs/results/*.json), for the website and dashboard."""
        from tripwire.eval.published import published_metrics

        return published_metrics(settings.data_dir.parent)

    @app.get("/analyze/status")
    def analyze_status():
        return {"ready": analyzer.ready(), "error": analyzer.error, "stored": False, "max_batch": 300,
                "reads": "headline + opening (two sentences, 600 characters), as for live news"}

    @app.post("/analyze/text")
    def analyze_text(req: AnalyzeRequest):
        try:
            return analyzer.analyse(req.title, req.text, req.source_type, req.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/analyze/batch")
    def analyze_batch(req: BatchRequest):
        try:
            rows = analyzer.analyse_batch([(i.title, i.text) for i in req.items], req.source_type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"stored": False, "n": len(rows), "rows": rows}

    @app.post("/analyze/portfolio")
    def analyze_portfolio(req: PortfolioRequest):
        try:
            return analyzer.analyse_portfolio(req.rows)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/companies/{ticker}/risk")
    def company_risk(ticker: str, days: int = Query(7, ge=1, le=90)):
        ticker = ticker.upper()
        if ticker not in tickers:
            raise HTTPException(404, "ticker not in the tracked universe")
        recent = store.query_signals(entity=ticker, since=now() - timedelta(days=days), limit=1000)
        return {
            "ticker": ticker,
            "window_days": days,
            "n_events": len(recent),
            "max_impact": max((s["impact_score"] for s in recent), default=None),
            "mean_sentiment": round(sum(s["sentiment_score"] for s in recent) / len(recent), 4) if recent else None,
            "by_event_type": _count(s["event_type"] for s in recent),
            "top_signals": sorted(recent, key=lambda s: -s["impact_score"])[:5],
        }

    @app.get("/ops/status")
    def ops_status():
        path = settings.var_dir / "collector_status.json"
        collectors = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return {"collectors": collectors, "store": store.health()}

    # ---- Module B ---------------------------------------------------------------------------------
    @app.get("/portfolio")
    def portfolio(include_positions: bool = False):
        return service().portfolio(include_positions)

    @app.get("/watchlist")
    def get_watchlist(status: str | None = Query(None, pattern="^(Red|Amber|Green)$"), limit: int = Query(100, ge=1)):
        days = load_yaml("book.yaml")["early_warning"]["lookback_days"]
        recent = store.query_signals(since=now() - timedelta(days=days), limit=100_000)
        out = service().watchlist(recent, now=now())
        out["names"] = [r for r in out["names"] if status is None or r["status"] == status][:limit]
        return out

    @app.get("/signals/{event_id}/stress-decision")
    def stress_decision(event_id: str):
        signal = store.get_signal(event_id)
        if signal is None:
            raise HTTPException(404, "unknown event_id")
        return service().decision(signal)

    @app.get("/signals/{event_id}/trace")
    def trace(event_id: str):
        signal = store.get_signal(event_id)
        if signal is None:
            raise HTTPException(404, "unknown event_id")
        return service().trace(signal)

    @app.post("/stress-test")
    def stress_test(req: StressRequest):
        svc = service()
        try:
            if req.event_id:
                return svc.run_event(req.event_id)
            if not req.event_type or req.impact is None:
                raise HTTPException(422, "give event_id, or event_type and impact for a what-if scenario")
            return svc.run_custom(req.event_type, req.impact, req.entity.upper() if req.entity else None,
                                  req.sector, [s.upper() for s in req.states], req.hard_flags)
        except KeyError:
            raise HTTPException(404, "unknown event_id") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/stress-test/{run_id}")
    def get_stress_run(run_id: str):
        run = store.get_stress_run(run_id)
        if run is None:
            raise HTTPException(404, "unknown run_id")
        return run

    @app.get("/stress-runs")
    def stress_runs(limit: int = Query(50, ge=1, le=500), event_id: str | None = None):
        runs = store.list_stress_runs(limit=limit, event_id=event_id)
        # Re-scoring re-clusters events, so a run can outlive the signal it was made for: say so, so the
        # dashboard links only to signals that still exist.
        for run in runs:
            run["signal_available"] = bool(run.get("event_id")) and store.get_signal(run["event_id"]) is not None
        return runs

    @app.websocket("/stream/signals")
    async def stream(ws: WebSocket, min_impact: float = 0):
        await ws.accept()
        cursor = datetime.now(UTC)
        ticks = 0
        try:
            while True:
                fresh = store.query_signals(min_impact=min_impact or None, updated_since=cursor, limit=200)
                cursor = datetime.now(UTC)
                for signal in fresh:
                    await ws.send_json({"type": "signal", "data": signal})
                ticks += 1
                if ticks % 3 == 0:
                    await ws.send_json({"type": "heartbeat", "time": cursor.isoformat()})
                await asyncio.sleep(5)
        except WebSocketDisconnect:
            return

    return app


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out
