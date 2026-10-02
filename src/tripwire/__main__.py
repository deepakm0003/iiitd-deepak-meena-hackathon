"""Command line entry point: python -m tripwire <command>."""

import argparse
import json
import logging
import signal
import sys
import threading

from tripwire import __version__
from tripwire.config import validate_configs
from tripwire.settings import get_settings


def _setup_logging(settings, verbose: bool = False) -> None:
    log_dir = settings.var_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(), logging.FileHandler(log_dir / "tripwire.log", encoding="utf-8")]
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_health(_: argparse.Namespace) -> int:
    from tripwire.factory import build_queue, build_store

    settings = get_settings()
    problems = validate_configs()
    store = build_store(settings).health()
    queue = build_queue(settings).health()
    report = {
        "version": __version__,
        "mode": settings.mode,
        "sources": settings.sources,
        "config": {"ok": not problems, "problems": problems},
        "store": store,
        "queue": queue,
        # Report presence only: secrets are never printed.
        "secrets": {
            "FINNHUB_API_KEY": "set" if settings.finnhub_api_key else "missing (only needed for live mode)",
            "SEC_USER_AGENT": "set" if settings.sec_user_agent else "missing (only needed for live mode)",
        },
    }
    ok = not problems and store.get("ok") and queue.get("ok")
    print(json.dumps(report, indent=2, default=str))
    print("Tripwire health: OK" if ok else "Tripwire health: FAILED", file=sys.stderr)
    return 0 if ok else 1


def cmd_collect(args: argparse.Namespace) -> int:
    from tripwire.factory import build_queue, build_sources, build_store
    from tripwire.ingestion.daemon import Scheduled, run_daemon
    from tripwire.ingestion.runner import requeue_unnormalized, run_normalizer, run_source

    settings = get_settings()
    _setup_logging(settings, args.verbose)
    live = args.live or settings.sources == "live"
    names = args.sources.split(",") if args.sources else None
    store, queue = build_store(settings), build_queue(settings)
    polled, streaming = build_sources(settings, names, live, args.bluesky_seconds)

    if args.daemon:
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        run_daemon(
            store,
            queue,
            [Scheduled(src, interval) for src, interval in polled],
            Scheduled(*streaming) if streaming else None,
            settings.var_dir / "collector_status.json",
            stop,
        )
        return 0

    requeue_unnormalized(store, queue)
    rows = []
    for source, _ in polled + ([streaming] if streaming else []):
        stats = run_source(store, queue, source)
        rows.append(stats)
    counts = run_normalizer(store, queue)
    print(f"{'source':10} {'status':6} {'fetched':>8} {'new':>6} {'dup':>6}  error")
    for s in rows:
        print(f"{s.source:10} {s.status:6} {s.fetched:8d} {s.inserted:6d} {s.duplicates:6d}  {s.error or ''}")
    print(f"normaliser: {counts}")
    print(f"store: {store.health()}")
    return 0 if all(s.status == "ok" for s in rows) else 1


def cmd_universe(args: argparse.Namespace) -> int:
    from tripwire.factory import build_http
    from tripwire.universe import load_universe, refresh_universe

    settings = get_settings()
    if args.refresh:
        if not settings.sec_user_agent:
            print("SEC_USER_AGENT must be set in .env to query SEC.", file=sys.stderr)
            return 1
        rows = refresh_universe(build_http(settings))
        print(f"wrote config/universe.yaml with {len(rows)} companies")
    companies = load_universe()
    sectors: dict[str, int] = {}
    for c in companies:
        sectors[c.sector] = sectors.get(c.sector, 0) + 1
    print(f"{len(companies)} companies, {sum(1 for c in companies if c.cik)} with CIK; by sector: {sectors}")
    return 0


def cmd_export_replay(args: argparse.Namespace) -> int:
    from pathlib import Path

    from tripwire.factory import build_store
    from tripwire.ingestion.replay_export import export_replay

    settings = get_settings()
    store = build_store(settings)
    sources = args.sources.split(",") if args.sources else ["gdelt", "finnhub", "edgar", "rbi", "fed", "bluesky"]
    counts = export_replay(store, Path(args.out), sources, args.per_source)
    print(f"exported {sum(counts.values())} documents to {args.out}: {counts}")
    return 0


def cmd_backfill_edgar(args: argparse.Namespace) -> int:
    """8-K history for the event study, plus filing text for every stored 8-K (live ones included)."""
    from datetime import UTC, datetime

    from tripwire.config import load_yaml
    from tripwire.factory import build_http, build_store
    from tripwire.ingestion.filing_text import fetch_filing_text
    from tripwire.ingestion.sources.edgar import EdgarSource
    from tripwire.universe import load_universe

    settings = get_settings()
    _setup_logging(settings)
    if not settings.sec_user_agent:
        print("SEC_USER_AGENT must be set in .env", file=sys.stderr)
        return 1
    store, http = build_store(settings), build_http(settings, sec_rate=args.rate)
    log = logging.getLogger("tripwire.backfill")
    if not args.texts_only:
        source = EdgarSource(http, load_universe(), load_yaml("edgar_items.yaml")["items"],
                             load_yaml("sources.yaml")["edgar"])
        since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        docs = source.backfill(since)
        new = sum(store.add_raw(d) is not None for d in docs)
        log.info("8-K backfill since %s: %d filings found, %d new", args.since, len(docs), new)
    if not args.skip_texts:
        todo = store.edgar_filings_missing_text(args.limit or 100_000)
        log.info("fetching text for %d filings", len(todo))
        ok = 0
        for i, item in enumerate(todo, 1):
            row = fetch_filing_text(http, item["cik"], item["accession"], item["primary_document"])
            store.add_filing_text(row)
            ok += row.status == "ok"
            if i % 100 == 0:
                log.info("texts: %d/%d done (%d ok)", i, len(todo), ok)
        log.info("texts finished: %d/%d ok", ok, len(todo))
    return 0


def cmd_prices(args: argparse.Namespace) -> int:
    from datetime import date

    from tripwire.factory import build_http, build_store
    from tripwire.market.prices import FRED_SERIES, MARKET_TICKERS, fetch_fred, fetch_yahoo
    from tripwire.universe import load_universe

    settings = get_settings()
    _setup_logging(settings)
    store, http = build_store(settings), build_http(settings)
    start = date.fromisoformat(args.since)
    tickers = [c.ticker for c in load_universe()] + MARKET_TICKERS
    n = store.upsert_prices(fetch_yahoo(tickers, start))
    for series in FRED_SERIES:
        n += store.upsert_prices(fetch_fred(http, series, start))
    coverage = store.price_coverage()
    missing = [t for t in tickers if t not in coverage]
    print(f"stored {n} observations for {len(coverage)} series; missing: {missing or 'none'}")
    for key in ("SPY", "JPM", "FRED:DGS10", "FRED:BAMLC0A0CM"):
        if key in coverage:
            print(f"  {key:16} {coverage[key][0]} .. {coverage[key][1]}  ({coverage[key][2]} days)")
    return 0 if not missing else 1


def cmd_gold(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime
    from pathlib import Path

    from tripwire import gold
    from tripwire.universe import load_universe

    settings = get_settings()
    gold_dir = settings.data_dir / "gold"
    candidates_path, gold_path = gold_dir / "candidates.jsonl", gold_dir / "gold.jsonl"
    if args.action == "sample":
        from tripwire.factory import build_store

        since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        docs = build_store(settings).iter_documents(since=since)
        rows = gold.sample_candidates(docs, args.n, seed=args.seed)
        existing = {r["key"] for r in gold.read_jsonl(candidates_path)}
        added = [r for r in rows if r["key"] not in existing]
        for row in added:
            gold.append_jsonl(Path(candidates_path), row)
        print(f"{len(docs)} documents since {args.since}; added {len(added)} candidates to {candidates_path}")
        return 0
    if args.action == "label":
        candidates = gold.read_jsonl(candidates_path)
        if not candidates:
            print(f"No candidates in {candidates_path}. Run `gold sample` first.", file=sys.stderr)
            return 1
        tickers = {c.ticker for c in load_universe()}
        print("Labelling. Guide: docs/labeling_guide.md. Commands at any prompt: s=skip  b=undo last  q=quit")
        n = gold.label_loop(candidates, gold_path, tickers)
        print()
        print(f"Saved {n} labels this session; total {len(gold.read_jsonl(gold_path))} in {gold_path}")
        return 0
    stats = gold.gold_stats(gold.read_jsonl(gold_path))
    print(json.dumps(stats, indent=2))
    return 0


def cmd_nlp(args: argparse.Namespace) -> int:
    """Annotate normalised documents (entities, event, sentiment, frame, embedding). Polls with --daemon."""
    import time

    from tripwire.factory import build_store
    from tripwire.nlp.device import limit_cpu_threads
    from tripwire.nlp.engine import NlpEngine
    from tripwire.nlp.linking import EntityLinker
    from tripwire.universe import load_universe

    settings = get_settings()
    _setup_logging(settings)
    log = logging.getLogger("tripwire.nlp")
    limit_cpu_threads()
    store = build_store(settings)
    ner = None
    if not args.no_ner:
        from tripwire.nlp.ner import GlinerNer

        ner = GlinerNer()
    engine = NlpEngine(EntityLinker(load_universe()), ner=ner)
    log.info("event classifier: %s | entity sentiment model: %s | NER: %s", engine.classifier.method,
             engine.sentiment.entity_model or "none (base FinBERT)", ner.name if ner else "off")
    total = 0
    while True:
        docs = store.documents_without_annotation(limit=args.batch)
        if docs:
            started = time.monotonic()
            total += store.add_annotations(engine.annotate(docs))
            log.info("annotated %d documents (%.1f docs/s); total this run %d",
                     len(docs), len(docs) / max(1e-6, time.monotonic() - started), total)
        if args.limit and total >= args.limit:
            break
        if not docs:
            if not args.daemon:
                break
            time.sleep(30)
    print(json.dumps(store.health(), indent=2))
    return 0


def cmd_train_events(args: argparse.Namespace) -> int:
    """Build weak-label data from the calibration period and train/compare the event classifiers."""
    from datetime import UTC, datetime

    from tripwire.factory import build_http, build_store
    from tripwire.nlp import train_events
    from tripwire.nlp import training_data as td
    from tripwire.nlp.classifier import REPORT_PATH, setfit_path

    settings = get_settings()
    _setup_logging(settings)
    store, http = build_store(settings), build_http(settings)
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    train = td.edgar_examples(store, utc(args.train_from), utc(args.train_to))
    train += td.twitter_examples(td.download_twitter_topic(http, "train"))
    train += td.seed_examples()
    valid = td.edgar_examples(store, utc(args.valid_from), utc(args.valid_to))
    valid += td.twitter_examples(td.download_twitter_topic(http, "valid"))
    train = td.balance(train, per_class=args.per_class)
    valid = td.balance(valid, per_class=args.per_class * 2, seed=29)
    report = train_events.run(train, valid, setfit_path(), REPORT_PATH)
    print(json.dumps({k: report[k] for k in ("train", "valid", "head", "setfit", "shipped_for_lite_mode")}, indent=2))
    return 0


def cmd_eval_sentiment(args: argparse.Namespace) -> int:
    from tripwire.eval.sentiment_eval import evaluate, load_sentfin
    from tripwire.nlp.sentiment import FinbertSentiment

    settings = get_settings()
    path = settings.data_dir / "raw" / "sentfin" / "SEntFiN-v1.1.csv"
    if not path.exists():
        print("Download SEntFiN first: kaggle datasets download ankurzing/aspect-based-sentiment-analysis-for-"
              "financial-news -p data/raw/sentfin --unzip", file=sys.stderr)
        return 1
    report = evaluate(load_sentfin(path), FinbertSentiment(), limit=args.limit)
    out = settings.data_dir.parent / "docs" / "results" / "sentiment_sentfin.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name in ("all", "multi_entity", "conflicting_sentiment"):
        part = report[name]
        print(f"{name:22} n={part['clause']['n']:5}  macro-F1 headline={part['headline']['macro_f1']:.3f} "
              f"{part['headline']['macro_f1_ci95']}  clause={part['clause']['macro_f1']:.3f} "
              f"{part['clause']['macro_f1_ci95']}")
    print(f"written to {out}")
    return 0


def cmd_train_sentiment(args: argparse.Namespace) -> int:
    from tripwire.config import load_yaml
    from tripwire.eval.sentiment_eval import baseline_predictions, load_sentfin
    from tripwire.nlp import train_sentiment as ts
    from tripwire.nlp.sentiment import FinbertSentiment

    settings = get_settings()
    _setup_logging(settings)
    rows = load_sentfin(settings.data_dir / "raw" / "sentfin" / "SEntFiN-v1.1.csv")
    test_rows = [r for r in rows if ts.split_of(r["title"]) == "test"]
    baselines = baseline_predictions(test_rows, FinbertSentiment())
    base = load_yaml("models.yaml")["sentiment"]["name"]
    root = settings.data_dir.parent
    report = ts.train(rows, base, root / "models" / "sentiment_entity", root / "docs" / "results" /
                      "sentiment_finetune.json", epochs=args.epochs, baseline=baselines)
    for part in ("test", "test_conflicting"):
        for name, res in report[part].items():
            print(f"{part:17} {name:15} n={res['n']:5} macro-F1={res['macro_f1']:.3f} {res['macro_f1_ci95']}")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    from tripwire.factory import build_store
    from tripwire.nlp.cluster_run import cluster_all
    from tripwire.nlp.clustering import EventClusterer

    store = build_store(get_settings())
    stats = cluster_all(store, EventClusterer(threshold=args.threshold))
    print(json.dumps(stats, indent=2))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    from tripwire.factory import build_store

    store = build_store(get_settings())
    print(json.dumps(store.health(), indent=2))
    print(f"\n{'started (UTC)':20} {'source':10} {'status':6} {'fetched':>8} {'new':>6} {'dup':>6}")
    for r in store.recent_runs(25):
        print(f"{r.started_at:%Y-%m-%d %H:%M:%S}  {r.source:10} {r.status:6} {r.fetched:8d} {r.inserted:6d} "
              f"{r.duplicates:6d}  {r.error or ''}")
    return 0


def cmd_not_yet(args: argparse.Namespace) -> int:
    print(f"'{args.command}' is not implemented yet; it arrives in Part 6 (dashboard).", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tripwire", description="Tripwire risk engine")
    parser.add_argument("--version", action="version", version=f"tripwire {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="check config, store and queue").set_defaults(func=cmd_health)

    collect = sub.add_parser("collect", help="run collectors once, or continuously with --daemon")
    collect.add_argument("--live", action="store_true", help="use live sources (default comes from settings)")
    collect.add_argument("--daemon", action="store_true", help="run forever on each source's interval")
    collect.add_argument("--sources", help="comma list: gdelt,finnhub,edgar,rss,bluesky (default: all)")
    collect.add_argument("--bluesky-seconds", type=float, default=None, help="Bluesky listening window")
    collect.add_argument("-v", "--verbose", action="store_true")
    collect.set_defaults(func=cmd_collect)

    universe = sub.add_parser("universe", help="show the company universe; --refresh pulls CIKs from SEC")
    universe.add_argument("--refresh", action="store_true")
    universe.set_defaults(func=cmd_universe)

    export = sub.add_parser("export-replay", help="write captured documents to data/replay for lite mode")
    export.add_argument("--out", default="data/replay/captured.jsonl")
    export.add_argument("--per-source", type=int, default=150)
    export.add_argument("--sources", help="comma list of source names (default: all)")
    export.set_defaults(func=cmd_export_replay)

    backfill = sub.add_parser("backfill-edgar", help="8-K history since a date, plus filing texts")
    backfill.add_argument("--since", default="2023-01-01")
    backfill.add_argument("--rate", type=float, default=3.0, help="SEC requests/second (limit is 10 per user)")
    backfill.add_argument("--texts-only", action="store_true", help="only fetch missing filing texts")
    backfill.add_argument("--skip-texts", action="store_true")
    backfill.add_argument("--limit", type=int, default=None, help="max filings to fetch text for")
    backfill.set_defaults(func=cmd_backfill_edgar)

    prices = sub.add_parser("prices", help="cache daily prices (Yahoo) and rates (FRED) locally")
    prices.add_argument("--since", default="2022-01-01")
    prices.set_defaults(func=cmd_prices)

    nlp = sub.add_parser("nlp", help="annotate documents: entities, event, sentiment, frame, embedding")
    nlp.add_argument("--batch", type=int, default=64)
    nlp.add_argument("--limit", type=int, default=None, help="stop after this many documents")
    nlp.add_argument("--daemon", action="store_true", help="keep polling for new documents")
    nlp.add_argument("--no-ner", action="store_true", help="skip GLiNER frame enrichment (faster on CPU)")
    nlp.set_defaults(func=cmd_nlp)

    train = sub.add_parser("train-events", help="train the event classifier on weak labels (GPU server)")
    train.add_argument("--train-from", default="2023-01-01")
    train.add_argument("--train-to", default="2024-12-31")
    train.add_argument("--valid-from", default="2025-01-01")
    train.add_argument("--valid-to", default="2025-06-30")
    train.add_argument("--per-class", type=int, default=64)
    train.set_defaults(func=cmd_train_events)

    eval_sent = sub.add_parser("eval-sentiment", help="entity-level sentiment accuracy on SEntFiN")
    eval_sent.add_argument("--limit", type=int, default=None)
    eval_sent.set_defaults(func=cmd_eval_sentiment)

    events_cmd = sub.add_parser("events", help="cluster annotated documents into events (full recompute)")
    events_cmd.add_argument("--threshold", type=float, default=0.72, help="cosine similarity to join an event")
    events_cmd.set_defaults(func=cmd_events)

    train_sent = sub.add_parser("train-sentiment", help="fine-tune FinBERT on (headline, entity) pairs (GPU)")
    train_sent.add_argument("--epochs", type=int, default=3)
    train_sent.set_defaults(func=cmd_train_sentiment)

    gold_cmd = sub.add_parser("gold", help="gold test set: sample candidates, label them, show stats")
    gold_cmd.add_argument("action", choices=["sample", "label", "stats"])
    gold_cmd.add_argument("--since", default="2026-09-28", help="sample documents published after this date")
    gold_cmd.add_argument("--n", type=int, default=200)
    gold_cmd.add_argument("--seed", type=int, default=7)
    gold_cmd.set_defaults(func=cmd_gold)

    sub.add_parser("status", help="store counts and recent collector runs").set_defaults(func=cmd_status)
    sub.add_parser("demo", help="replay the demo storyline and open the dashboard (Part 6)").set_defaults(
        func=cmd_not_yet
    )
    args = parser.parse_args(argv)
    if get_settings().force_ipv4:
        from tripwire.netfix import prefer_ipv4

        prefer_ipv4()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
