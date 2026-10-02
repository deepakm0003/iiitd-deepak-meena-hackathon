"""Event frame: who did what, how much, when, where, and how certain the text is (factuality).

Rule-based slot filling from the text plus the linked entities; GLiNER spans (Part 2b) can add or override
slots later. Factuality matters for risk: "reportedly in talks" or "3 stocks to buy" must not trigger a
stress test the way "files for Chapter 11" does.
"""

import re
from dataclasses import asdict, dataclass, field

MONEY = re.compile(
    r"(?:US)?\$\s?\d[\d,]*(?:\.\d+)?\s?(?:trillion|billion|million|bn|mn|m|b|k)?\b"
    r"|₹\s?\d[\d,]*(?:\.\d+)?\s?(?:crore|lakh|billion|million)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:trillion|billion|million)\s(?:dollars|rupees|euros)\b",
    re.IGNORECASE,
)
PERCENT = re.compile(r"[-+]?\d+(?:\.\d+)?\s?(?:%|percent\b|basis points\b|bps\b)", re.IGNORECASE)
TARGET = re.compile(
    r"\b(?:to acquire|acquires|acquiring|to buy|buys|buying|takeover of|merger with|merge with|bid for)\s+"
    r"((?:[A-Z][\w&.\-]*\s?){1,5})"
)

OPINION = re.compile(
    r"\?\s*$|^\s*(why|how)\b|^\s*\d+\s+\w+.*\b(stocks?|shares|picks|reasons|things)\b|"
    r"\b(stocks? to (buy|sell|watch)|should you buy|"
    r"is it time to|here'?s (why|how|what)|what to (know|expect)|versus industry peers|buy the dip|top picks?|"
    r"best .{0,20}stocks?|my favorite|price target|analyst(s)? (says?|sees)|(bull|bear) case|explained|opinion|"
    r"(?-i:could|might|may) (?!not\b)\w+|speculation)\b",
    re.IGNORECASE,
)
DENIED = re.compile(r"\b(denies|denied|refutes|rejects (the )?(report|claims?)|no plans to|not in talks)\b", re.I)
# Rumour = an unconfirmed report attributed to sources about a specific pending event. Forecasts and
# "could/might" speculation are opinion, not rumour.
RUMOUR = re.compile(
    r"\b(reportedly|report(s|ed)? say|sources (said|say)|people familiar|according to (people|sources)|"
    r"(is|are) (said|reported) to|(considering|exploring|weighing) (a|an|options|selling|strategic|bids?|sale)|"
    r"mulls?|in (early )?talks|rumou?rs?|eyes (?!on\b)\w+)\b",
    re.IGNORECASE,
)
# In the lead, only explicit sourcing/talks language counts: modal verbs ("could", "may") are too common
# in ordinary reporting to mark an item as a rumour.
STRONG_RUMOUR = re.compile(
    r"\b(reportedly|sources (said|say)|people familiar|according to (people|sources)|(is|are) (said|reported) to|"
    r"in (early )?talks|considering a|exploring a|weighing a)\b",
    re.IGNORECASE,
)
ANNOUNCED = re.compile(
    r"\b(announces?|announced|plans? to|will|to (acquire|buy|launch|cut|raise|close|open)|agrees? to|"
    r"expects?|guidance|outlook|proposes?|sets?|schedules?|intends? to)\b",
    re.IGNORECASE,
)


def factuality(title: str, lead: str = "") -> tuple[str, str]:
    """Return (label, cue). Title decides first; the lead only adds hedging cues."""
    for label, pattern in (("opinion", OPINION), ("denied", DENIED), ("rumour", RUMOUR), ("announced", ANNOUNCED)):
        if match := pattern.search(title):
            return label, match.group().strip()
    if match := STRONG_RUMOUR.search(lead or ""):
        return "rumour", match.group().strip()
    return "confirmed", ""


@dataclass
class EventFrame:
    actor: str | None = None          # primary linked entity (ticker) or None for macro items
    target: str | None = None         # counterparty / acquisition target, when stated
    amounts: list[str] = field(default_factory=list)
    percentages: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    factuality: str = "confirmed"
    factuality_cue: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def extract_frame(title: str, lead: str, actor: str | None, places: list[str] | None = None) -> EventFrame:
    text = f"{title}. {lead}" if lead else title
    label, cue = factuality(title, lead)
    target = TARGET.search(text)
    return EventFrame(
        actor=actor,
        target=target.group(1).strip(" .,") if target else None,
        amounts=_unique(m.group().strip() for m in MONEY.finditer(text))[:5],
        percentages=_unique(m.group().strip() for m in PERCENT.finditer(text))[:5],
        places=(places or [])[:5],
        factuality=label,
        factuality_cue=cue,
    )


def _unique(values) -> list[str]:
    return list(dict.fromkeys(values))
