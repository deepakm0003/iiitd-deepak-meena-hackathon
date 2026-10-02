"""Command line entry point: python -m tripwire <command>."""

import argparse
import json
import sys

from tripwire import __version__
from tripwire.config import validate_configs
from tripwire.factory import build_queue, build_store
from tripwire.settings import get_settings


def cmd_health(_: argparse.Namespace) -> int:
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


def cmd_not_yet(args: argparse.Namespace) -> int:
    part = {"collect": "Part 1 (data pipeline)", "demo": "Part 6 (dashboard)"}[args.command]
    print(f"'{args.command}' is not implemented yet; it arrives in {part}.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tripwire", description="Tripwire risk engine")
    parser.add_argument("--version", action="version", version=f"tripwire {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="check config, store and queue").set_defaults(func=cmd_health)
    sub.add_parser("collect", help="run collectors (Part 1)").set_defaults(func=cmd_not_yet)
    sub.add_parser("demo", help="replay the demo storyline and open the dashboard (Part 6)").set_defaults(
        func=cmd_not_yet
    )
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
