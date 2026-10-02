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

    sub.add_parser("status", help="store counts and recent collector runs").set_defaults(func=cmd_status)
    sub.add_parser("demo", help="replay the demo storyline and open the dashboard (Part 6)").set_defaults(
        func=cmd_not_yet
    )
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
