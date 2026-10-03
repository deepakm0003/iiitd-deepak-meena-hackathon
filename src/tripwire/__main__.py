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
    if args.action == "stratify":
        from tripwire.factory import build_store
        from tripwire.nlp.filing_lead import with_filing_leads

        store = build_store(settings)
        predicted = {a["dedup_key"]: a["event_type"] for a in store.get_annotations()}
        docs = with_filing_leads(store, store.iter_documents())  # labellers see the press release, not the 8-K title
        rows = gold.sample_stratified(docs, predicted, seed=args.seed)
        if gold.read_jsonl(gold_path):
            print(f"{gold_path} already has labels; refusing to replace the candidates", file=sys.stderr)
            return 1
        candidates_path.parent.mkdir(parents=True, exist_ok=True)
        candidates_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        report = gold.candidate_report(rows)
        (gold_dir / "candidates_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
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
    if args.action in ("check", "agreement"):
        check_path, silver_path = gold_dir / "human_check.jsonl", gold_dir / "silver_llm.jsonl"
        sample = gold.human_check_sample(gold.read_jsonl(candidates_path))
        if args.action == "check":
            from tripwire.universe import load_universe

            print(f"Human check: {len(sample)} items, labelled blind. Commands: s=skip  b=undo last  q=quit")
            n = gold.label_loop(sample, check_path, {c.ticker for c in load_universe()}, quick=args.quick)
            print(f"Saved {n} labels this session; total {len(gold.read_jsonl(check_path))} of {len(sample)}")
            return 0
        report = gold.agreement(gold.read_jsonl(check_path), gold.read_jsonl(silver_path))
        out = settings.data_dir.parent / "docs" / "results" / "silver_agreement.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "event_disagreements"}, indent=2))
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
    from tripwire.nlp.filing_lead import with_filing_leads

    for source in (args.reannotate or "").split(","):
        if source.strip():
            log.info("deleted %d annotations from source %s for re-annotation",
                     store.delete_annotations(source.strip()), source.strip())
    total = 0
    while True:
        docs = with_filing_leads(store, store.documents_without_annotation(limit=args.batch))
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


def cmd_eval_events(args: argparse.Namespace) -> int:
    """Selective-classification report on the validation split: head vs head + abstention + zero-shot check."""
    from datetime import UTC, datetime

    from tripwire.config import load_yaml
    from tripwire.eval.event_selective import report
    from tripwire.factory import build_http, build_store
    from tripwire.nlp import training_data as td
    from tripwire.nlp.classifier import EventClassifier

    settings = get_settings()
    store, http = build_store(settings), build_http(settings)
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    valid = td.edgar_examples(store, utc(args.valid_from), utc(args.valid_to))
    valid += td.twitter_examples(td.download_twitter_topic(http, "valid"))
    valid = td.balance(valid, per_class=args.per_class * 2, seed=29)  # the same split as train-events
    texts = [e.text for e in valid]
    clf = EventClassifier()
    heads = [r.probabilities for r in clf.predict(texts)]
    zss = [r.probabilities for r in clf.predict_zero_shot(texts)]
    cfg = load_yaml("models.yaml")["event_classifier"]
    out = report([e.label for e in valid], heads, zss, [e.origin for e in valid], set(cfg["verify"]["classes"]),
                 cfg["min_confidence"], cfg["verify"]["min_p"])
    path = settings.data_dir.parent / "docs" / "results" / "event_selective.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: {m: v for m, v in out[k].items() if m != "per_class"} for k in ("before", "after")},
                     indent=2))
    return 0


def cmd_eval_gold(args: argparse.Namespace) -> int:
    """Evaluate the deployed pipeline on the human gold set (test split); choose thresholds on the dev split."""
    from tripwire import gold
    from tripwire.config import load_yaml
    from tripwire.eval import gold_eval as ge
    from tripwire.factory import build_store
    from tripwire.nlp.classifier import EventClassifier
    from tripwire.nlp.engine import classifier_text
    from tripwire.nlp.filing_lead import with_filing_leads

    settings = get_settings()
    gold_dir = settings.data_dir / "gold"
    labels_path = gold_dir / args.labels
    labels = gold.read_jsonl(labels_path)
    if not labels:
        print(f"No labels in {labels_path}: nothing to evaluate.", file=sys.stderr)
        return 1
    annotators = sorted({row.get("annotator", "unknown") for row in labels})
    silver = any("LLM" in a for a in annotators)
    candidates = {c["key"]: c for c in gold.read_jsonl(gold_dir / "candidates.jsonl")}
    store = build_store(settings)
    ann = {a["dedup_key"]: a for a in store.get_annotations()}
    docs = {d.dedup_key: d for d in store.iter_documents()}
    rows = []
    for lab in labels:
        a, c = ann.get(lab["key"]), candidates.get(lab["key"])
        if a is None or c is None:
            continue
        rows.append({"key": lab["key"], "split": lab["split"], "stratum": c["stratum"],
                     "stratum_population": c["stratum_population"], "gold": lab["event_type"],
                     "pred": a["event_type"], "method": a["event_method"], "entity_gold": lab["entity"],
                     "entity_pred": a["primary"], "sentiment_gold": lab["sentiment"],
                     "sentiment_pred": {"negative": -1, "neutral": 0, "positive": 1}[a["sentiment_label"]],
                     "factuality_gold": lab["factuality"], "factuality_pred": (a.get("frame") or {}).get("factuality")})
    classes = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]
    test = [r for r in rows if r["split"] == "test"]
    # Threshold check: ML-classified items only (rules and 8-K items do not use thresholds).
    ml = [r for r in rows if not r["method"].startswith(("8k_item", "rule", "8k:"))]
    texts = [classifier_text(d) for d in with_filing_leads(store, [docs[r["key"]] for r in ml])]
    clf = EventClassifier()
    keep = [i for i, t in enumerate(texts) if t]
    heads = clf.predict([texts[i] for i in keep])
    zss = clf.predict_zero_shot([texts[i] for i in keep])
    for i, h, z in zip(keep, heads, zss, strict=True):
        ml[i]["head"], ml[i]["zs"] = h.probabilities, z.probabilities
    ml = [r for r in ml if "head" in r]
    cfg = load_yaml("models.yaml")["event_classifier"]
    verify = set(cfg["verify"]["classes"])
    entity_ok = [r["entity_gold"] == r["entity_pred"] or (r["entity_gold"] == "OTHER" and r["entity_pred"] == "NONE")
                 for r in test]
    n_test = max(1, len(test))
    report = {
        "labels": {"n": len(labels), "joined": len(rows), "test": len(test), "dev": len(rows) - len(test),
                   "file": labels_path.name, "annotators": annotators,
                   "kind": "LLM-annotated SILVER labels, not human gold; see the human agreement check" if silver
                   else "human gold labels"},
        "note": "population = corpus-level estimates (stratified sampling, see eval/gold_eval.py); on_sample = "
                "metrics on the labelled test items, which over-represent rare classes by design. This is the full "
                "11-class gold result, distinct from the 7-class validation-proxy result in event_selective.json.",
        "population_test": ge.population(test, classes),
        "on_sample_test": ge.on_sample([r["gold"] for r in test], [r["pred"] for r in test]) if test else None,
        "entity_accuracy_test": round(sum(entity_ok) / n_test, 4),
        "sentiment_accuracy_test": round(sum(r["sentiment_gold"] == r["sentiment_pred"] for r in test) / n_test, 4),
        "factuality_accuracy_test": round(sum(r["factuality_gold"] == r["factuality_pred"] for r in test) / n_test, 4),
        "thresholds": {
            "current": {"min_p": cfg["min_confidence"], "verifier_min_p": cfg["verify"]["min_p"]},
            "sweep_dev": ge.threshold_sweep([r for r in ml if r["split"] == "dev"], verify),
            "sweep_test_for_reference_only": ge.threshold_sweep([r for r in ml if r["split"] == "test"], verify),
        },
    }
    out = settings.data_dir.parent / "docs" / "results" / ("silver_eval.json" if silver else "gold_eval.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("labels", "entity_accuracy_test", "sentiment_accuracy_test")}, indent=2))
    print(json.dumps(report["population_test"], indent=1))
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


def cmd_calibrate(_: argparse.Namespace) -> int:
    """Event study + Impact calibration (calibration period) + out-of-time validation."""
    from tripwire.factory import build_store
    from tripwire.scoring.calibrate import run, save_outputs

    settings = get_settings()
    final, report, returns_ = run(build_store(settings))
    save_outputs(settings.data_dir.parent, final, report, returns_)
    print(json.dumps({k: report[k] for k in ("event_study", "counts", "model_selection_inner_check_spearman",
                                             "chosen", "identifiable_factors", "weights")}, indent=2))
    test = report["test"]
    print("\nOUT-OF-TIME TEST (|SCAR| vs Impact):")
    for name in ("final", "expert", "fitted", "blended"):
        t = test[name]
        print(f"  {name:8} n={t['n']} spearman={t['spearman']} {t['spearman_ci95']} AUC={t['auc_large_move']} "
              f"precision@7={t['trigger_precision_impact_ge_7']} (n={t['n_triggered']}, "
              f"base {t['base_rate_large_move']})")
    for name, b in test["baselines"].items():
        print(f"  baseline {name:26} spearman={b['spearman']} {b['spearman_ci95']} AUC={b['auc_large_move']}")
    print("  buckets:", test["final"]["buckets"])
    print("  ablation (spearman without factor):", test["ablation_drop_one_factor"])
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    """Cluster -> score -> store signals -> export JSONL. With --daemon, repeat every --every seconds."""
    import time

    from tripwire.factory import build_store
    from tripwire.scoring.impact import ImpactModel
    from tripwire.scoring.pipeline import score_cycle

    settings = get_settings()
    _setup_logging(settings)
    log = logging.getLogger("tripwire.score")
    store = build_store(settings)
    model = ImpactModel.load(settings.data_dir.parent / "models" / "impact_model.json")
    export = settings.var_dir / "signals.jsonl"
    from tripwire.stress.service import load_service

    stress = load_service(store, settings.data_dir)  # Module B runs automatically when the book exists
    while True:
        stats = score_cycle(store, model, export, stress)
        log.info("score cycle: %s", stats)
        if not args.daemon:
            print(json.dumps(stats, indent=2))
            return 0
        time.sleep(args.every)


def cmd_api(args: argparse.Namespace) -> int:
    import uvicorn

    from tripwire.api.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


def cmd_book(args: argparse.Namespace) -> int:
    """Build the synthetic wholesale book. --from-raw re-derives merchant features from the Kaggle data."""
    from pathlib import Path

    from tripwire.config import load_yaml
    from tripwire.portfolio.book import build_book, build_merchant_table, market_snapshot, save_book

    settings = get_settings()
    root = settings.data_dir.parent
    table_csv = settings.data_dir / "merchant_features.csv"
    fy = load_yaml("book.yaml")["as_of_fiscal_year"]
    if args.from_raw:

        from tripwire.portfolio import merchants as m

        raw = settings.data_dir / "raw" / "kaggle_transactions"
        derived = settings.var_dir / "derived"
        derived.mkdir(parents=True, exist_ok=True)
        if args.reaggregate or not (derived / "mccs.pkl").exists():  # the 13 M-row pass takes minutes
            monthly, customers, states, mccs = m.aggregate(raw / "transactions_data.csv",
                                                           raw / "train_fraud_labels.json")
            for name, frame in (("monthly", monthly), ("customers", customers), ("states", states), ("mccs", mccs)):
                frame.to_pickle(derived / f"{name}.pkl")
        else:
            import pandas as pd

            monthly, customers = pd.read_pickle(derived / "monthly.pkl"), pd.read_pickle(derived / "customers.pkl")
        _, report = m.validate_risk_model(monthly, customers)
        out = root / "docs" / "results" / "merchant_risk_validation.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"merchant risk model, out-of-time AUC {report['test']['auc']} {report['test']['auc_ci95']}")
        table = build_merchant_table(derived, settings.data_dir / "mcc_sector_map.csv", fy)
        table.to_csv(table_csv, index_label="merchant_id")
        print(f"wrote {len(table)} merchants to {table_csv}")
        if args.merchants_only:
            return 0
    import csv

    from tripwire.factory import build_store
    from tripwire.universe import load_universe

    rows = []
    with open(Path(table_csv), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({k: (r[k] if k in ("sector", "state") else float(r[k])) for k in r})
    universe = {c.ticker: {"sector": c.sector} for c in load_universe()}
    tickers = [e["ticker"] for e in load_yaml("book.yaml")["tranche2"]["equities"]]
    book = build_book(rows, market_snapshot(build_store(settings), tickers), universe)
    save_book(book, settings.data_dir / "book.json")
    print(json.dumps({"totals": book["totals"], "capital": book["capital"],
                      "tranche1_grades": _count(o["grade"] for o in book["tranche1"])}, indent=2))
    return 0


def cmd_market_inputs(_: argparse.Namespace) -> int:
    """Measure historical-analog shocks and equity betas from the price cache -> data/market_inputs.json."""
    from datetime import UTC, datetime

    from tripwire.factory import build_store
    from tripwire.market.prices import MARKET_TICKERS
    from tripwire.portfolio.book import SECTOR_ETF
    from tripwire.stress.market import measure_analogs, measure_betas
    from tripwire.universe import load_universe

    settings = get_settings()
    store = build_store(settings)
    companies = load_universe()
    names = [*(c.ticker for c in companies), *MARKET_TICKERS, "FRED:DGS10", "FRED:VIXCLS"]
    prices = {t: {b.date: b.adj_close for b in store.get_prices(t)} for t in names}
    prices = {t: p for t, p in prices.items() if p}
    sector_etf = {c.ticker: SECTOR_ETF[c.sector] for c in companies}
    sector_etf["KRE"] = "XLF"
    out = {
        "measured_at": datetime.now(UTC).isoformat(),
        "provenance": "MEASURED from public daily prices (Yahoo Finance, FRED) in the local cache",
        "analogs": measure_analogs(prices),
        "betas": measure_betas(prices, [*(c.ticker for c in companies), "KRE"], sector_etf),
    }
    path = settings.data_dir / "market_inputs.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["analogs"], indent=1))
    print({t: out["betas"][t] for t in ("JPM", "NVDA", "XOM", "KRE") if t in out["betas"]})
    return 0


def _count(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


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
    nlp.add_argument("--reannotate", metavar="SOURCE", help="delete and redo annotations of one source first")
    nlp.set_defaults(func=cmd_nlp)

    train = sub.add_parser("train-events", help="train the event classifier on weak labels (GPU server)")
    train.add_argument("--train-from", default="2023-01-01")
    train.add_argument("--train-to", default="2024-12-31")
    train.add_argument("--valid-from", default="2025-01-01")
    train.add_argument("--valid-to", default="2025-06-30")
    train.add_argument("--per-class", type=int, default=64)
    train.set_defaults(func=cmd_train_events)

    eval_ev = sub.add_parser("eval-events", help="selective-classification report for the event classifier")
    eval_ev.add_argument("--valid-from", default="2025-01-01")
    eval_ev.add_argument("--valid-to", default="2025-06-30")
    eval_ev.add_argument("--per-class", type=int, default=64)
    eval_ev.set_defaults(func=cmd_eval_events)

    eval_gold = sub.add_parser("eval-gold", help="evaluate the event pipeline on the gold (or silver) labels")
    eval_gold.add_argument("--labels", default="gold.jsonl", help="labels file in data/gold (silver_llm.jsonl)")
    eval_gold.set_defaults(func=cmd_eval_gold)

    eval_sent = sub.add_parser("eval-sentiment", help="entity-level sentiment accuracy on SEntFiN")
    eval_sent.add_argument("--limit", type=int, default=None)
    eval_sent.set_defaults(func=cmd_eval_sentiment)

    book = sub.add_parser("book", help="build the synthetic wholesale book (Module B)")
    book.add_argument("--from-raw", action="store_true", help="re-derive merchant features from the Kaggle data")
    book.add_argument("--reaggregate", action="store_true", help="redo the pass over the raw transactions")
    book.add_argument("--merchants-only", action="store_true", help="with --from-raw: stop after the merchant table")
    book.set_defaults(func=cmd_book)

    sub.add_parser("market-inputs", help="measure historical-analog shocks and betas (price cache)").set_defaults(
        func=cmd_market_inputs
    )

    score = sub.add_parser("score", help="cluster events, score Impact, store and export signals")
    score.add_argument("--daemon", action="store_true")
    score.add_argument("--every", type=int, default=120, help="seconds between cycles with --daemon")
    score.set_defaults(func=cmd_score)

    api = sub.add_parser("api", help="serve the signals API (OpenAPI docs at /docs)")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.set_defaults(func=cmd_api)

    sub.add_parser("calibrate", help="event study, Impact calibration and out-of-time validation").set_defaults(
        func=cmd_calibrate
    )

    events_cmd = sub.add_parser("events", help="cluster annotated documents into events (full recompute)")
    events_cmd.add_argument("--threshold", type=float, default=0.72, help="cosine similarity to join an event")
    events_cmd.set_defaults(func=cmd_events)

    train_sent = sub.add_parser("train-sentiment", help="fine-tune FinBERT on (headline, entity) pairs (GPU)")
    train_sent.add_argument("--epochs", type=int, default=3)
    train_sent.set_defaults(func=cmd_train_sentiment)

    gold_cmd = sub.add_parser("gold", help="gold test set: sample candidates, label them, show stats")
    gold_cmd.add_argument("action", choices=["stratify", "sample", "label", "check", "agreement", "stats"])
    gold_cmd.add_argument("--since", default="2026-09-28", help="sample documents published after this date")
    gold_cmd.add_argument("--n", type=int, default=200)
    gold_cmd.add_argument("--seed", type=int, default=7)
    gold_cmd.add_argument("--quick", action="store_true", help="check: ask only entity and event type")
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
