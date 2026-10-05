"""Export a small, self-contained demo database from the live store, so the dashboard runs without our server.

Copies the signals first seen in the last N days (default 14), every stress run whose signal is in the snapshot plus
all what-if runs, and the price history (used for entity importance when analysing uploads). Documents and
annotations are not copied: each signal carries its own source titles, links and evidence. The collector status
file is copied for the Data sources page.

Run on the server:  python scripts/make_demo_snapshot.py --days 14
Writes data/demo/tripwire_demo.db.gz (committed; the commit guard allows this one file up to 15 MB),
collector_status.json and snapshot.json. `python -m tripwire demo` unpacks it.
"""

import argparse
import gzip
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tripwire.adapters.sql_store import SqlStore
from tripwire.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "demo"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()
    settings = get_settings()
    source = settings.database_url.removeprefix("sqlite:///")
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "tripwire_demo.db"
    target.unlink(missing_ok=True)
    schema = SqlStore(f"sqlite:///{target.as_posix()}")
    schema.init()  # same schema as the live store
    schema.engine.dispose()  # release the connection, or the copy below finds the file locked
    since = (datetime.now(UTC) - timedelta(days=args.days)).isoformat(sep=" ")
    con = sqlite3.connect(target)
    con.execute("ATTACH DATABASE ? AS live", (source,))
    # the window, plus the Western Alliance 8-K (2023) the site falls back to when no recent run qualifies
    con.execute("INSERT INTO signals SELECT * FROM live.signals WHERE first_seen >= ? OR event_id = ?",
                (since, "evt_600c4206f3fa"))
    con.execute("""INSERT INTO stress_runs SELECT * FROM live.stress_runs
                   WHERE event_id IS NULL OR event_id IN (SELECT event_id FROM signals)""")
    con.execute("INSERT INTO prices_daily SELECT * FROM live.prices_daily")
    con.commit()
    tables = ("signals", "stress_runs", "prices_daily")
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    con.execute("DETACH DATABASE live")
    con.execute("VACUUM")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # everything into the main file before it is compressed
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()
    for extra in ("-wal", "-shm"):
        Path(f"{target}{extra}").unlink(missing_ok=True)
    with open(target, "rb") as raw, gzip.open(OUT / "tripwire_demo.db.gz", "wb", compresslevel=9) as packed:
        shutil.copyfileobj(raw, packed)
    status = settings.var_dir / "collector_status.json"
    if status.exists():
        shutil.copy(status, OUT / "collector_status.json")
    meta = {"exported_at": datetime.now(UTC).isoformat(), "days": args.days, "counts": counts,
            "size_mb": round(target.stat().st_size / 1e6, 1),
            "gz_mb": round((OUT / "tripwire_demo.db.gz").stat().st_size / 1e6, 1)}
    target.unlink()
    (OUT / "snapshot.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
