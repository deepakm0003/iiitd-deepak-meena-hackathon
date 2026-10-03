"""Weak-label training data for the event classifier (training only; the gold set is the test data).

Sources, each recorded per example so the model card can report the mix:
  1. 8-K filings in the CALIBRATION period: item number -> class (config/event_rules.yaml item_map); the
     input is the press release (or main text) with 8-K headings stripped so the label cannot leak.
  2. zeroshot/twitter-financial-news-topic (MIT): 20 topics mapped onto our 11 classes by the FROZEN map
     below (fixed before any test result was seen); ambiguous topics are dropped, not guessed.
  3. Author-written seed examples (config/seed_examples.yaml) for classes weak labels barely cover.
"""

import csv
import io
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tripwire.config import load_yaml
from tripwire.nlp.text import strip_filing_leakage
from tripwire.settings import ROOT

TWITTER_TOPIC_URL = "https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic/resolve/main/topic_{split}.csv"
TWITTER_DIR = ROOT / "data" / "raw" / "twitter_topic"

# FROZEN on 2026-10-02, before any evaluation. None = dropped (no clean correspondence).
TWITTER_TOPIC_MAP: dict[int, str | None] = {
    0: "Other",                 # Analyst Update
    1: "Macroeconomic",         # Fed | Central Banks
    2: None,                    # Company | Product News (mixes launches, deals, operations)
    3: None,                    # Treasuries | Corporate Debt (rates vs credit: ambiguous)
    4: "Other",                 # Dividend
    5: "Earnings",              # Earnings
    6: None,                    # Energy | Oil
    7: None,                    # Financials
    8: "Macroeconomic",         # Currencies
    9: None,                    # General News | Opinion
    10: None,                   # Gold | Metals | Materials
    11: "Other",                # IPO
    12: "Regulatory/Legal",     # Legal | Regulation
    13: "Merger/Acquisition",   # M&A | Investments
    14: "Macroeconomic",        # Macro
    15: None,                   # Markets
    16: "Geopolitical",         # Politics (noisy: includes domestic politics; noted in the model card)
    17: "Management Change",    # Personnel Change
    18: "Other",                # Stock Commentary
    19: "Other",                # Stock Movement
}
MAX_CHARS = 600


@dataclass(frozen=True)
class Example:
    text: str
    label: str
    origin: str  # 8k:<item> | twitter:<topic id> | seed


def download_twitter_topic(http, split: str) -> Path:
    TWITTER_DIR.mkdir(parents=True, exist_ok=True)
    path = TWITTER_DIR / f"topic_{split}.csv"
    if not path.exists():
        path.write_bytes(http.get(TWITTER_TOPIC_URL.format(split=split)).content)
    return path


def twitter_examples(path: Path) -> list[Example]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    out = []
    for row in reader:
        label = TWITTER_TOPIC_MAP.get(int(row["label"]))
        if label:
            out.append(Example(row["text"].strip(), label, f"twitter:{row['label']}"))
    return out


def seed_examples() -> list[Example]:
    return [Example(text, label, "seed") for label, texts in load_yaml("seed_examples.yaml").items() for text in texts]


def edgar_examples(store, start: datetime, end: datetime) -> list[Example]:
    """8-K weak labels in [start, end]. Filings whose items map to nothing (7.01/8.01/9.01 only) are skipped;
    with several mapped items the most severe class wins, as at inference time."""
    from tripwire.nlp.events import EventRules

    rules = EventRules()
    out = []
    for doc in store.iter_documents(since=start, until=end):
        if doc.source != "edgar":
            continue
        mapped = [rules.item_map[i] for i in doc.hints.get("items", []) if i in rules.item_map]
        if not mapped:
            continue
        best = max(mapped, key=lambda m: rules.prior(m["class"], m["subtype"]))
        text = store.get_filing_text(doc.hints.get("accession", ""))
        body = strip_filing_leakage((text.exhibit_text or text.main_text) if text else "")
        if len(body) < 80:
            continue
        item = next(i for i in doc.hints["items"] if rules.item_map.get(i) == best)
        out.append(Example(body[:MAX_CHARS], best["class"], f"8k:{item}"))
    return out


def balance(examples: list[Example], per_class: int, seed: int = 13) -> list[Example]:
    """At most `per_class` examples per label, keeping seed examples first (they cover rare classes)."""
    rng = random.Random(seed)
    by_label: dict[str, list[Example]] = {}
    for ex in examples:
        by_label.setdefault(ex.label, []).append(ex)
    out = []
    for items in by_label.values():
        seeds = [e for e in items if e.origin == "seed"]
        rest = [e for e in items if e.origin != "seed"]
        rng.shuffle(rest)
        out += (seeds + rest)[:per_class]
    rng.shuffle(out)
    return out


def describe(examples: list[Example]) -> dict:
    return {
        "n": len(examples),
        "by_label": dict(Counter(e.label for e in examples).most_common()),
        "by_origin": dict(Counter(e.origin.split(":")[0] for e in examples).most_common()),
    }


# ---- recipe v3 (2026-10-03): repaired Twitter mappings + in-domain examples first ------------------------
# Chosen on the human gold DEV split (docs/results/event_head_experiment_human.json): with the bge-base encoder,
# dev accuracy 0.690 -> 0.714 and macro-F1 0.601 -> 0.629 against the previous head.
MNA_CUES = re.compile(r"\b(acqui|merger|merge|takeover|buyout|tender offer|to buy|bid for|deal for|stake in)",
                      re.IGNORECASE)
GEO_CUES = re.compile(r"\b(tariff|sanction|war\b|china|russia|ukraine|iran|israel|trade (war|deal|talks)|export|"
                      r"embargo|nato|military|geopolit)", re.IGNORECASE)
NEAR_DUPLICATE_COSINE = 0.85
OPINION_OTHER_CAP = 400


def twitter_examples_repaired(path: Path) -> list[Example]:
    """'M&A | Investments' keeps only texts with deal cues; 'Politics' only texts with geopolitical cues
    (the definitions card excludes domestic politics from Geopolitical)."""
    out = []
    for ex in twitter_examples(path):
        topic = int(ex.origin.split(":")[1])
        if topic == 13 and not MNA_CUES.search(ex.text):
            continue
        if topic == 16 and not GEO_CUES.search(ex.text):
            continue
        out.append(ex)
    return out


def in_domain_examples(store, docs, exclude_keys: set[str]) -> tuple[list[Example], list[Example]]:
    """Rule-labelled items from our own feeds, and listicle / opinion headlines as Other.

    Evaluation items and their near-duplicates (same normalised title, or MiniLM cosine >= 0.85 to any of them)
    are excluded, so no test or dev item leaks into training. `docs` must be in store order with filing leads."""
    import numpy as np

    from tripwire.ids import normalize_title
    from tripwire.nlp.engine import classifier_text
    from tripwire.nlp.frame import OPINION

    ann = {a["dedup_key"]: a for a in store.get_annotations()}
    by_key = {d.dedup_key: d for d in docs}
    emb = np.array([ann[k]["embedding"] for k in exclude_keys if k in ann and ann[k].get("embedding")],
                   dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    titles = {normalize_title(by_key[k].title) for k in exclude_keys if k in by_key}

    def excluded(d) -> bool:
        if d.dedup_key in exclude_keys or normalize_title(d.title) in titles:
            return True
        e = ann.get(d.dedup_key, {}).get("embedding")
        if not e:
            return False
        v = np.asarray(e, dtype=np.float32)
        return float((emb @ (v / np.linalg.norm(v))).max()) >= NEAR_DUPLICATE_COSINE

    rules, other = [], []
    for d in docs:
        if d.source == "edgar" or excluded(d):
            continue
        a = ann.get(d.dedup_key)
        if not a:
            continue
        text = classifier_text(d)
        if a["event_method"].startswith("rule:"):
            rules.append(Example(text[:MAX_CHARS], a["event_type"], f"rule:{a['event_method'][5:]}"))
        elif OPINION.search(d.title):
            other.append(Example(text[:MAX_CHARS], "Other", "opinion_headline"))
    random.Random(3).shuffle(other)
    return rules, other[:OPINION_OTHER_CAP]


def recipe_v3(edgar: list[Example], twitter_path: Path, rules: list[Example], other: list[Example]) -> list[Example]:
    """In-domain examples get the priority balance() gives seeds; Twitter fills the remaining slots."""
    promoted = [Example(e.text, e.label, "seed") for e in rules + other]
    return balance(edgar + twitter_examples_repaired(twitter_path) + seed_examples() + promoted, per_class=150)
