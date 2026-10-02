"""Deterministic event evidence: 8-K item mapping (layer 1) and high-precision text rules (layer 2).

These layers decide the class when they fire, with a stated confidence; everything else goes to the ML
classifier (layer 3, SetFit / zero-shot). Every decision records which item or rule produced it, so the
dashboard can show *why* an item was classified the way it was.
"""

import re
from dataclasses import dataclass

from tripwire.config import load_yaml
from tripwire.models import Document

ITEM_CONFIDENCE = 0.95  # the filer itself declared the item: strongest evidence we have
RULE_CONFIDENCE = 0.90


@dataclass(frozen=True)
class EventEvidence:
    event_type: str
    subtype: str
    source: str  # "8k_item:2.02" | "rule:bankruptcy"
    confidence: float


class EventRules:
    def __init__(self, rules_cfg: dict | None = None, taxonomy: dict | None = None) -> None:
        rules_cfg = rules_cfg or load_yaml("event_rules.yaml")
        taxonomy = taxonomy or load_yaml("taxonomy.yaml")
        self.item_map = rules_cfg["item_map"]
        self.rules = [
            (r["id"], r["class"], r["subtype"], re.compile(r["pattern"], re.IGNORECASE)) for r in rules_cfg["rules"]
        ]
        self.severity: dict[tuple[str, str | None], float] = {}
        for cls in taxonomy["classes"]:
            self.severity[(cls["name"], None)] = cls["severity_prior"]
            for subtype, prior in cls.get("subtypes", {}).items():
                self.severity[(cls["name"], subtype)] = prior

    def prior(self, event_type: str, subtype: str | None = None) -> float:
        return self.severity.get((event_type, subtype), self.severity.get((event_type, None), 0.1))

    def evidence(self, doc: Document, text: str | None = None) -> list[EventEvidence]:
        found: list[EventEvidence] = []
        if doc.source == "edgar":
            for item in doc.hints.get("items", []):
                if mapped := self.item_map.get(item):
                    found.append(EventEvidence(mapped["class"], mapped["subtype"], f"8k_item:{item}", ITEM_CONFIDENCE))
        haystack = text if text is not None else f"{doc.title}. {doc.lead}"
        for rule_id, cls, subtype, pattern in self.rules:
            if pattern.search(haystack):
                found.append(EventEvidence(cls, subtype, f"rule:{rule_id}", RULE_CONFIDENCE))
        return found

    def decide(self, evidence: list[EventEvidence]) -> EventEvidence | None:
        """Pick one class: highest severity prior wins (tie-breaker 1 of the labelling guide), then confidence.

        'Other' from an 8-K item (e.g. 1.01 material agreement) is weak and yields to any specific text rule.
        """
        if not evidence:
            return None
        specific = [e for e in evidence if e.event_type != "Other"] or evidence
        return max(specific, key=lambda e: (self.prior(e.event_type, e.subtype), e.confidence))
