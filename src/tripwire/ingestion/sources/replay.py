"""Replay previously captured real documents from data/replay/*.jsonl (lite mode and the demo).

Documents keep their original `source` (e.g. 'finnhub'), so everything downstream behaves exactly as live.
Cursor: number of documents already emitted (files are read in name order, lines in time order).
"""

import json
from pathlib import Path

from tripwire.models import RawDocument
from tripwire.ports.source import FetchResult


class ReplaySource:
    name = "replay"
    source_type = "news"

    def __init__(self, replay_dir: Path, batch_size: int = 1000) -> None:
        self.replay_dir = replay_dir
        self.batch_size = batch_size

    def _all(self) -> list[RawDocument]:
        docs = []
        for path in sorted(self.replay_dir.glob("*.jsonl")):
            with open(path, encoding="utf-8") as fh:
                docs.extend(RawDocument.model_validate(json.loads(line)) for line in fh if line.strip())
        return sorted(docs, key=lambda d: d.published_at)

    def fetch(self, cursor: str | None) -> FetchResult:
        offset = int(cursor or 0)
        docs = self._all()[offset : offset + self.batch_size]
        return FetchResult(docs, str(offset + len(docs)))
