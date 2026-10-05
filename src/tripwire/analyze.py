"""Analyse uploaded text with the production models, in memory only.

The same code as the live pipeline runs on the upload: entity linking, event rules and the event classifier with
its verifier, entity-level sentiment, factuality, the Impact Score (formula + measured calibration), the stress
trigger and, for stress-mappable events, a Module B stress run on the book. Nothing is written to the store: the
upload does not become a signal, an event or a stress run, so it never mixes with collected data or evaluations.

The classifier reads what it reads for live news: the headline and the opening (production lead: two sentences,
600 characters). Novelty is measured against the last 7 days of collected items about the same subject;
corroboration is one source, by definition.
"""

import hashlib
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.ingestion.normalize import clean_text, make_lead
from tripwire.models import Document
from tripwire.nlp.clustering import credibility_of, publisher_of
from tripwire.nlp.events import EventRules
from tripwire.scoring import records as rec
from tripwire.scoring.impact import ImpactModel, volume_factor
from tripwire.scoring.signals import signal_payload

SOURCE_TYPES = ("news", "filing", "regulator", "social")
MAX_TITLE = 400
MAX_TEXT = 50_000
MAX_BATCH = 300
NOVELTY_LOOKBACK = timedelta(days=7)


class Analyzer:
    def __init__(self, store, stress, root: Path, engine=None, model: ImpactModel | None = None, clock=None) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))  # demo mode: the snapshot time
        self.stress = stress
        self.root = root
        self._engine = engine
        self._model = model
        self._universe = None
        self._importance = None
        self._lock = threading.Lock()
        self._ready = engine is not None and model is not None
        self.error: str | None = None
        self._severity = EventRules()
        self._cfg = load_yaml("impact_weights.yaml")
        self._confirmed = set(load_yaml("event_rules.yaml").get("confirmed_sources", []))
        self._tiers = load_yaml("credibility.yaml")["tiers"]

    # ---- model loading (once per process; the models take a minute and about 2 GB) --------------------
    def ready(self) -> bool:
        return self._ready

    def warm(self) -> None:
        """Load every model now (they load lazily on first use), so the first upload is answered in seconds."""
        with self._lock:
            try:
                self._load()
            except ImportError as exc:  # core install without the ML stack (requirements-research.txt)
                self.error = (f"The NLP models are not installed ({exc.name}). Install them with "
                              "`pip install -r requirements-research.txt` to use Analyse.")
                return
            probe = Document(raw_id=-1, dedup_key="warmup", source="upload", source_type="news",
                             title="Federal Reserve holds rates steady", lead="Officials signalled two cuts this year.",
                             published_at=datetime.now(UTC))
            self._engine.annotate([probe])
            self._ready = True

    def _load(self) -> None:
        from tripwire.universe import load_universe

        if self._engine is None:
            from tripwire.nlp.engine import NlpEngine
            from tripwire.nlp.linking import EntityLinker

            try:
                from tripwire.nlp.ner import GlinerNer

                ner = GlinerNer()
            except Exception:  # NER only enriches frame slots; analysis works without it
                ner = None
            self._engine = NlpEngine(EntityLinker(load_universe()), ner=ner)
        if self._model is None:
            self._model = ImpactModel.load(self.root / "models" / "impact_model.json")
        if self._universe is None:
            self._universe = {c.ticker: c for c in load_universe()}
            period = tuple(date.fromisoformat(d[:10]) for d in self._model.calibration_period)
            self._importance = rec.entity_importance(self.store, list(self._universe), period)

    # ---- analysis ----------------------------------------------------------------------------------
    def analyse(self, title: str, text: str = "", source_type: str = "news", url: str | None = None,
                stress: bool = True) -> dict:
        [result] = self._analyse_many([(title, text)], source_type, url, stress=stress)
        return result

    def analyse_batch(self, items: list[tuple[str, str]], source_type: str = "news") -> list[dict]:
        if len(items) > MAX_BATCH:
            raise ValueError(f"at most {MAX_BATCH} rows per batch")
        return [_row(i, r) for i, r in enumerate(self._analyse_many(items, source_type, None, stress=False), 1)]

    def _analyse_many(self, items: list[tuple[str, str]], source_type: str, url: str | None,
                      stress: bool) -> list[dict]:
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {SOURCE_TYPES}")
        now = self.clock()
        docs = []
        for i, (title, text) in enumerate(items):
            title, text = clean_text(title)[:MAX_TITLE], clean_text(text)[:MAX_TEXT]
            if not title and not text:
                raise ValueError(f"item {i + 1}: give a headline or some text")
            if not title:  # no headline: the first sentence is the headline, as for social posts
                lead_all = make_lead(text, max_sentences=1, max_chars=MAX_TITLE)
                title, text = lead_all, text[len(lead_all.rstrip("…")):].strip()
            key = hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()
            docs.append(Document(raw_id=-(i + 1), dedup_key=key, source="upload", source_type=source_type,
                                 title=title, lead=make_lead(text) if text else "", url=url, published_at=now,
                                 hints={}))
        if self.error:
            raise ValueError(self.error)
        with self._lock:
            try:
                self._load()
            except ImportError as exc:
                self.error = (f"The NLP models are not installed ({exc.name}). Install them with "
                              "`pip install -r requirements-research.txt` to use Analyse.")
                raise ValueError(self.error) from None
            annotations = [a.model_dump(mode="json") for a in self._engine.annotate(docs)]
        out = []
        recent_by_key: dict[str, list[dict]] = {}
        for doc, ann in zip(docs, annotations, strict=True):
            key = ann["primary"]
            if key != "NONE" and key not in recent_by_key:  # one query per subject per request
                recent_by_key[key] = self.store.get_annotations(since=now - NOVELTY_LOOKBACK, primary=key)
            recent = recent_by_key.get(key, [])
            signal = self._signal(doc, ann, recent, source_type, url)
            decision = self.stress.decision(signal) if signal and self.stress else None
            run = None
            if stress and signal and self.stress and signal["event_type"] in self.stress.shocks["classes"]:
                run = self.stress.run_signal(signal)
                run.pop("positions", None)  # 300+ rows; the top contributors and totals are what is shown
            out.append({
                "analysed_at": now.isoformat(),
                "stored": False,
                "input": {"title": doc.title, "lead_used": doc.lead, "source_type": source_type, "url": url},
                "annotation": _annotation_view(ann),
                "signal": signal,
                "decision": decision,
                "stress": run,
                "reason_no_signal": None if signal else (
                    "No subject: the text is not about a tracked company and has no market-wide evidence, so "
                    "the live pipeline would not create a signal from it."),
            })
        return out

    def _signal(self, doc: Document, ann: dict, recent: list[dict], source_type: str, url: str | None):
        key = ann["primary"]
        if key == "NONE":
            return None
        if key == "MACRO":
            relevance, link_conf, e_factor = ann.get("macro_evidence", 0.0), 1.0, rec.MACRO_IMPORTANCE
        else:
            ents = [e for e in ann["entities"] if e["ticker"] == key]
            relevance = max((e["relevance"] for e in ents), default=0.0)
            link_conf = max((e["link_confidence"] for e in ents), default=0.0)
            e_factor = self._importance.get(key, 0.5)
        emb = ann.get("embedding") or []
        same = [a.get("embedding") for a in recent if a.get("embedding")]
        novelty = 1.0 - max((sum(x * y for x, y in zip(emb, e, strict=True)) for e in same), default=0.0)
        publisher = publisher_of("upload", url, {})
        record = {
            "event_id": "upl_" + doc.dedup_key[:12],
            "key": key,
            "first_seen": doc.published_at,
            "event_type": ann["event_type"],
            "event_subtype": ann.get("event_subtype"),
            "event_method": ann["event_method"],
            "event_confidence": ann["event_confidence"],
            "sentiment": round(ann["sentiment"], 4),
            "relevance": relevance,
            "link_confidence": link_conf,
            "corroboration": 0.4,  # one source (EventClusterer.corroboration with a single publisher)
            "n_docs": 1,
            "n_publishers": 1,
            "sources": ["upload"],
            "doc_ids": [doc.raw_id],
            "factors": {
                "S_severity": self._severity.prior(ann["event_type"], ann.get("event_subtype")),
                "M_sentiment_magnitude": min(1.0, abs(ann["sentiment"])),
                "E_entity_importance": e_factor,
                "N_novelty": round(max(0.0, min(1.0, novelty)), 4),
                "V_volume_corroboration": round(volume_factor(1, 1), 4),
                "Q_source_credibility": credibility_of("upload", source_type, publisher, self._tiers),
                "H_historical_reaction": None,
            },
        }
        return signal_payload(record, [ann], {doc.raw_id: doc}, self._model, self._universe, self._cfg,
                              self._confirmed)


    # ---- uploaded portfolio ----------------------------------------------------------------------------
    def analyse_portfolio(self, rows: list[dict], top_runs: int = 5) -> dict:
        """The user's own book against the live signals: exposures, the early-warning watchlist of their names,
        which of this week's stress-mappable signals would trigger a stress test on THEIR book, and the stress
        runs for the most important of those. In memory only."""
        from tripwire.portfolio.upload import build_uploaded_book
        from tripwire.stress.service import StressService
        from tripwire.stress.trigger import scenario_from_signal

        if self.stress is None:
            raise ValueError("the stress engine is not configured on this server")
        universe = {c["ticker"]: c for c in load_yaml("universe.yaml").get("companies", [])}
        book = build_uploaded_book(rows, self.stress.book["market_snapshot"], universe)
        svc = StressService(self.store, self.root / "data", book=book)
        now = self.clock()
        signals = self.store.query_signals(since=now - timedelta(days=30), limit=100_000, exclude_other=True)
        week = [s for s in signals if datetime.fromisoformat(s["first_seen_at"]) >= now - timedelta(days=7)
                and s["event_type"] in svc.shocks["classes"]]
        decided = [(s, svc.decision(s)) for s in week]
        triggered = sorted([(s, d) for s, d in decided if d["trigger"]], key=lambda x: -x[0]["impact_score"])
        touching = [(s, d) for s, d in decided if d["exposure"]["direct"] > 0 or d["exposure"]["sector"] > 0
                    or d["exposure"]["geography"] > 0]
        runs = []
        for s, d in triggered[:top_runs]:
            run = svc._run(scenario_from_signal(s, svc.analogs, svc.shocks), "upload", d, persist=False)
            runs.append({
                "event_id": s["event_id"], "headline": s["headline"], "event_type": s["event_type"],
                "subject": s["primary_entity"], "impact": s["impact_score"], "first_seen_at": s["first_seen_at"],
                "pnl_total": run["pnl_total"], "ecl_change": run["ecl_change"],
                "cet1_ratio_before": run["capital"]["cet1_ratio_before"],
                "cet1_ratio_after": run["capital"]["cet1_ratio_after"],
                "n_positions_affected": run["n_positions_affected"],
                "pnl_by_asset_class": run["pnl_by_asset_class"], "top_contributors": run["top_contributors"][:5],
                "reverse_stress": run.get("reverse_stress"), "decision": d,
            })
        wl = svc.watchlist(signals, now=now)
        return {
            "analysed_at": now.isoformat(),
            "stored": False,
            "portfolio": svc.portfolio(include_positions=True),
            "watchlist": {**wl, "names": wl["names"][:100]},
            "events": {"checked": len(week), "touching_your_book": len(touching), "would_trigger": len(triggered),
                       "runs": runs},
        }


def _annotation_view(ann: dict) -> dict:
    keep = ("primary", "event_type", "event_subtype", "event_method", "event_confidence", "event_probabilities",
            "sentiment", "sentiment_label", "sentiment_evidence", "frame", "event_evidence", "macro_evidence",
            "model_versions")
    view = {k: ann.get(k) for k in keep}
    view["entities"] = [{k: e.get(k) for k in ("ticker", "sector", "link_confidence", "relevance", "in_title",
                                                "method", "sentiment")} for e in ann.get("entities", [])]
    return view


def _row(i: int, r: dict) -> dict:
    a, s, d = r["annotation"], r["signal"] or {}, r["decision"] or {}
    return {
        "row": i,
        "title": r["input"]["title"],
        "subject": a["primary"],
        "company": (s.get("company") or {}).get("name"),
        "event_type": a["event_type"],
        "event_subtype": a["event_subtype"],
        "decided_by": a["event_method"],
        "alert_tier": s.get("alert_tier", "none"),
        "evidence": (a.get("event_evidence") or {}).get("phrase", ""),
        "sentiment": round(a["sentiment"], 3),
        "factuality": (a.get("frame") or {}).get("factuality"),
        "impact": s.get("impact_score"),
        "p_large_move": s.get("p_large_move"),
        "risk_level": s.get("risk_level"),
        "stress_trigger": d.get("trigger") if d else None,
        "note": r["reason_no_signal"],
    }
