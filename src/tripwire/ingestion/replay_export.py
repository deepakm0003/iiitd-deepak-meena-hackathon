"""Export captured real documents to data/replay/*.jsonl for lite mode, tests and the demo.

Kept deliberately small (repository hygiene): headlines plus a short excerpt, with source URLs for
attribution. Bluesky items are already pseudonymised at capture (hashed author, no URL).
"""

from pathlib import Path

from tripwire.ports import Store

MAX_TEXT = 600


def export_replay(store: Store, out_path: Path, sources: list[str], per_source: int) -> dict[str, int]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    docs = []
    for source in sources:
        picked = list(store.iter_raw(source=source, limit=per_source))
        counts[source] = len(picked)
        docs.extend(picked)
    docs.sort(key=lambda d: d.published_at)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        for doc in docs:
            trimmed = doc.model_copy(update={"text": doc.text[:MAX_TEXT]})
            fh.write(trimmed.model_dump_json() + "\n")
    return counts
