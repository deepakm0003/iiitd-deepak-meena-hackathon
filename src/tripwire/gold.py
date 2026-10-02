"""Gold-set tooling: sample candidates, label them by hand in the terminal, and re-label for agreement.

Labels are the TEST data for the NLP engine (see docs/labeling_guide.md). Rules enforced here:
- Items are keyed by the document dedup key, so labels survive across databases (laptop vs server).
- No model output is shown while labelling (labels are written before predictions are seen).
- The dev/test split is a fixed function of the key (25% dev for tuning thresholds, 75% test).
- Sampling is mostly random, plus a recorded 'boosted' stratum that over-samples rare event types, so the
  test set is not 90% earnings and stock-pick listicles. Each item keeps its stratum for honest reporting.
"""

import hashlib
import json
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tripwire.config import load_yaml
from tripwire.ids import normalize_title
from tripwire.models import Document

RARE_EVENT_CUES = re.compile(
    r"bankrupt|chapter 11|default|downgrad|going concern|liquidity|insolven|sanction|tariff|\bwar\b|missile|"
    r"invasion|lawsuit|\bsued\b|probe|investigat|\bfined?\b|settle|breach|hack|outage|recall|strike|hurricane|"
    r"flood|wildfire|earthquake|shortage|acquir|merger|takeover|buyout|resign|steps down|appoint|layoff",
    re.IGNORECASE,
)
ENTITY_SPECIAL = {"m": "MACRO", "o": "OTHER", "n": "NONE"}
SENTIMENT = {"-": -1, "0": 0, "+": 1}
FACTUALITY = {"c": "confirmed", "a": "announced", "r": "rumour", "d": "denied", "o": "opinion"}


def split_for(key: str) -> str:
    return "dev" if int(hashlib.sha256(key.encode()).hexdigest(), 16) % 4 == 0 else "test"


# Share of the sample per source, so one high-volume feed (Finnhub) cannot crowd out filings, regulators
# and social posts. Slots a source cannot fill go to the remaining pool.
SOURCE_QUOTAS = {"finnhub": 0.40, "gdelt": 0.25, "edgar": 0.10, "rbi": 0.05, "fed": 0.05, "bluesky": 0.15}


def sample_candidates(
    docs: list[Document],
    n: int,
    boost_share: float = 0.4,
    seed: int = 7,
    quotas: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    quotas = SOURCE_QUOTAS if quotas is None else quotas
    unique: dict[str, Document] = {}
    for doc in docs:  # one item per normalised title (syndicated copies count once)
        unique.setdefault(normalize_title(doc.title), doc)
    pool = list(unique.values())
    rng.shuffle(pool)
    picked: dict[str, tuple[Document, str]] = {}

    def take(candidates: list[Document], k: int) -> None:
        boosted = [d for d in candidates if RARE_EVENT_CUES.search(f"{d.title} {d.lead}")]
        target = len(picked) + k
        for doc in boosted[: round(k * boost_share)]:
            picked.setdefault(doc.dedup_key, (doc, "boosted"))
        for doc in candidates:
            if len(picked) >= target:
                break
            picked.setdefault(doc.dedup_key, (doc, "random"))

    for source, share in quotas.items():
        take([d for d in pool if d.source == source], round(n * share))
    take([d for d in pool if d.dedup_key not in picked], n - len(picked))  # fill unused slots
    return [
        {
            "key": doc.dedup_key,
            "source": doc.source,
            "source_type": doc.source_type,
            "published_at": doc.published_at.isoformat(),
            "title": doc.title,
            "lead": doc.lead,
            "url": doc.url,
            "stratum": stratum,
            "split": split_for(doc.dedup_key),
        }
        for doc, stratum in picked.values()
    ]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _ask(prompt: str, valid: Callable[[str], bool], ask: Callable[[str], str]) -> str:
    while True:
        answer = ask(prompt).strip()
        if answer in {"s", "q", "b"} or valid(answer):
            return answer
        print("  ? not valid, try again (s = skip, b = back, q = quit)")


def label_loop(
    candidates: list[dict[str, Any]],
    gold_path: Path,
    tickers: set[str],
    ask: Callable[[str], str] = input,
    annotator: str = "deepak",
) -> int:
    classes = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]
    done = {row["key"] for row in read_jsonl(gold_path)}
    todo = [c for c in candidates if c["key"] not in done]
    menu = "  ".join(f"{i}={name}" for i, name in enumerate(classes, 1))
    history: list[int] = []  # indices of items saved in this session, for 'b' (undo last save)
    i = 0
    while i < len(todo):
        item = todo[i]
        print(f"\n[{len(done) + len(history) + 1}] {item['source']} | {item['published_at'][:16]}")
        print(f"  TITLE: {item['title']}")
        if item.get("lead"):
            print(f"  LEAD : {item['lead'][:400]}")
        answers = []
        prompts = [
            ("  entity (ticker | m=MACRO o=OTHER n=NONE): ",
             lambda a: a.upper() in tickers or a.lower() in ENTITY_SPECIAL),
            (f"  {menu}\n  event #: ", lambda a: a.isdigit() and 1 <= int(a) <= len(classes)),
            ("  sentiment (- 0 +): ", lambda a: a in SENTIMENT),
            ("  factuality (c=confirmed a=announced r=rumour d=denied o=opinion): ", lambda a: a in FACTUALITY),
            ("  material for a risk analyst? (y/n): ", lambda a: a in {"y", "n"}),
        ]
        for prompt, valid in prompts:
            answer = _ask(prompt, valid, ask)
            answers.append(answer)
            if answer in {"q", "s", "b"}:
                break
        command = answers[-1] if answers[-1] in {"q", "s", "b"} else None
        if command == "q":
            break
        if command == "s":
            i += 1
            continue
        if command == "b":
            if history:
                _drop_last(gold_path)
                i = history.pop()
                print("  (undid the last saved label)")
            continue
        entity, event, sentiment, factuality, material = answers
        note = ask("  note (optional, Enter to skip): ").strip()
        append_jsonl(gold_path, {
            "key": item["key"],
            "split": item["split"],
            "stratum": item["stratum"],
            "source": item["source"],
            "title": item["title"],
            "entity": ENTITY_SPECIAL.get(entity.lower(), entity.upper()),
            "event_type": classes[int(event) - 1],
            "sentiment": SENTIMENT[sentiment],
            "factuality": FACTUALITY[factuality],
            "material": material == "y",
            "note": note,
            "annotator": annotator,
            "labeled_at": datetime.now(UTC).isoformat(),
        })
        history.append(i)
        i += 1
    return len(history)


def _drop_last(path: Path) -> None:
    rows = read_jsonl(path)[:-1]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def gold_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def count(field: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            out[str(row[field])] = out.get(str(row[field]), 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    return {"n": len(rows), **{f: count(f) for f in ("split", "stratum", "source", "event_type", "factuality",
                                                     "sentiment", "material")}}
