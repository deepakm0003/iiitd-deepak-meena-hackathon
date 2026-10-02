"""FastAPI app: the Risk Engine's output, for Module B and the dashboard (OpenAPI docs at /docs).

  GET  /health                       store and pipeline health
  GET  /signals                      list, filters: min_impact, event_type, entity, since, limit
  GET  /signals/{event_id}           one signal with breakdown, evidence and documents
  GET  /companies/{ticker}/risk      rolling 7-day view for one company
  GET  /ops/status                   collector status (per-source last run, failures, pauses)
  WS   /stream/signals               pushes new or changed signals (checks every 5 s), heartbeat every 15 s
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect

from tripwire.config import load_yaml
from tripwire.factory import build_store
from tripwire.settings import get_settings

EVENT_TYPES = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]


def create_app(store=None) -> FastAPI:
    settings = get_settings()
    store = store or build_store(settings)
    tickers = {c["ticker"] for c in load_yaml("universe.yaml").get("companies", [])}
    app = FastAPI(title="Tripwire Risk Engine API", version="1.0",
                  description="Structured, explainable financial risk signals from news, filings and social posts.")

    @app.get("/health")
    def health():
        return {"status": "ok", "store": store.health(), "time": datetime.now(UTC).isoformat()}

    @app.get("/signals")
    def list_signals(
        min_impact: float | None = Query(None, ge=1, le=10),
        event_type: str | None = None,
        entity: str | None = Query(None, description="ticker, MACRO"),
        since: datetime | None = None,
        limit: int = Query(100, ge=1, le=1000),
    ):
        if event_type and event_type not in EVENT_TYPES:
            raise HTTPException(422, f"unknown event_type; choose from {EVENT_TYPES}")
        return store.query_signals(min_impact=min_impact, event_type=event_type,
                                   entity=entity.upper() if entity else None, since=since, limit=limit)

    @app.get("/signals/{event_id}")
    def get_signal(event_id: str):
        signal = store.get_signal(event_id)
        if signal is None:
            raise HTTPException(404, "unknown event_id")
        return signal

    @app.get("/companies/{ticker}/risk")
    def company_risk(ticker: str, days: int = Query(7, ge=1, le=90)):
        ticker = ticker.upper()
        if ticker not in tickers:
            raise HTTPException(404, "ticker not in the tracked universe")
        recent = store.query_signals(entity=ticker, since=datetime.now(UTC) - timedelta(days=days), limit=1000)
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
