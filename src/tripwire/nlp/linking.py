"""Entity linking with confidence, NIL, and relevance (which company is the item really about?).

Evidence, from strongest to weakest (confidences in config/linking.yaml, assumption A-16):
  EDGAR filer > cashtag > long alias / SEC legal name > acronym (case-sensitive) > ambiguous alias in
  corporate context > GDELT-tagged organisation not in our text > ambiguous alias alone > source hint only.
Entities whose best evidence falls below the NIL threshold are not linked: a wrong link is worse than none,
because it would send a stress test to the wrong company.

Relevance (A-17) separates the subject of the headline from a passing mention, so that "3 stocks like JPM"
or "...unlike Apple" does not count as news about that company.
"""

import re
from dataclasses import dataclass, field

from tripwire.config import load_yaml
from tripwire.ingestion.matching import CASHTAG
from tripwire.models import Document
from tripwire.nlp.text import split_sentences
from tripwire.universe import Company


@dataclass(frozen=True)
class Mention:
    surface: str
    location: str  # title | lead | hint
    start: int
    method: str
    confidence: float


@dataclass
class LinkedEntity:
    ticker: str
    cik: int | None
    sector: str
    link_confidence: float
    relevance: float
    in_title: bool
    method: str
    mentions: list[Mention] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.link_confidence * self.relevance


@dataclass(frozen=True)
class _Alias:
    ticker: str
    pattern: re.Pattern
    kind: str  # long_alias | acronym | ambiguous


class EntityLinker:
    def __init__(self, companies: list[Company], cfg: dict | None = None) -> None:
        cfg = cfg or load_yaml("linking.yaml")
        self.conf = cfg["link_confidence"]
        self.rel = cfg["relevance"]
        self.companies = {c.ticker: c for c in companies}
        self.gdelt_boilerplate = set(cfg.get("gdelt_boilerplate_tickers", []))
        ambiguous = set(cfg.get("ambiguous_aliases", []))
        context = cfg.get("corporate_context", [])
        self._context = re.compile(r"\b(" + "|".join(map(re.escape, context)) + r")\b", re.IGNORECASE)
        self._aliases: list[_Alias] = []
        for company in companies:
            for name in company.all_names:
                if name in ambiguous:
                    kind = "ambiguous"
                elif name.isupper() and len(name) <= 5:
                    kind = "acronym"
                else:
                    kind = "long_alias"
                flags = 0 if kind in {"ambiguous", "acronym"} else re.IGNORECASE
                pattern = re.compile(r"(?<![\w&])" + re.escape(name) + r"(?![\w&])", flags)
                self._aliases.append(_Alias(company.ticker, pattern, kind))
        # Longest aliases first so "Bank of America" wins over a shorter overlapping alias.
        self._aliases.sort(key=lambda a: -len(a.pattern.pattern))

    # ------------------------------------------------------------------------------------------------
    def link(self, doc: Document) -> list[LinkedEntity]:
        mentions: dict[str, list[Mention]] = {}
        for location, text in (("title", doc.title), ("lead", doc.lead)):
            self._text_mentions(text, location, mentions)
        self._hint_mentions(doc, mentions)

        entities = []
        for ticker, found in mentions.items():
            best = max(found, key=lambda m: m.confidence)
            textual = [m for m in found if m.location != "hint"]
            confidence = min(0.99, best.confidence + self.conf["extra_mention_bonus"] * max(0, len(textual) - 1))
            if best.method == "filer":
                confidence = 1.0
            if confidence < self.conf["nil_threshold"]:
                continue
            company = self.companies[ticker]
            entities.append(
                LinkedEntity(
                    ticker=ticker,
                    cik=company.cik,
                    sector=company.sector,
                    link_confidence=round(confidence, 3),
                    relevance=round(self._relevance(doc, found), 3),
                    in_title=any(m.location == "title" for m in found),
                    method=best.method,
                    mentions=found,
                )
            )
        return sorted(entities, key=lambda e: -e.score)

    def primary(self, doc: Document) -> LinkedEntity | None:
        entities = self.link(doc)
        return entities[0] if entities else None

    # ------------------------------------------------------------------------------------------------
    def _text_mentions(self, text: str, location: str, out: dict[str, list[Mention]]) -> None:
        if not text:
            return
        taken: list[tuple[int, int]] = []
        for match in CASHTAG.finditer(text):
            ticker = match.group(1).replace(".", "-")
            if ticker in self.companies:
                self._add(out, ticker, Mention(match.group(), location, match.start(), "cashtag",
                                               self.conf["cashtag"]))
                taken.append(match.span())
        sentences = split_sentences(text)
        for alias in self._aliases:
            for match in alias.pattern.finditer(text):
                if any(s <= match.start() < e for s, e in taken):
                    continue  # inside a longer alias already matched
                taken.append(match.span())
                if alias.kind == "ambiguous":
                    sentence = next((s for s in sentences if match.group() in s), text)
                    corporate = bool(self._context.search(sentence)) or bool(
                        re.search(re.escape(match.group()) + r"\s*(Inc|Corp|Co)\b|'s (shares|stock|CEO)", sentence)
                    )
                    method = "ambiguous_in_context" if corporate else "ambiguous"
                else:
                    method = alias.kind
                self._add(out, alias.ticker, Mention(match.group(), location, match.start(), method,
                                                     self.conf[method]))

    def _hint_mentions(self, doc: Document, out: dict[str, list[Mention]]) -> None:
        hints = doc.hints
        if doc.source == "edgar" and hints.get("ticker") in self.companies:
            self._add(out, hints["ticker"], Mention(hints["ticker"], "hint", 0, "filer", self.conf["filer"]))
        for ticker in hints.get("matched_tickers", []):  # GDELT's own organisation tagging
            if ticker in self.gdelt_boilerplate and ticker not in out:
                continue  # tagged from page boilerplate, not named in the text
            if ticker in self.companies:
                self._add(out, ticker, Mention(ticker, "hint", 0, "gdelt_org", self.conf["gdelt_org"]))
        for ticker in hints.get("related", []):  # Finnhub: weak, often just the queried ticker
            if ticker in self.companies:
                self._add(out, ticker, Mention(ticker, "hint", 0, "source_hint", self.conf["source_hint"]))

    @staticmethod
    def _add(out: dict[str, list[Mention]], ticker: str, mention: Mention) -> None:
        out.setdefault(ticker, []).append(mention)

    def _relevance(self, doc: Document, mentions: list[Mention]) -> float:
        if any(m.method == "filer" for m in mentions):
            return self.rel["filer"]
        title_mentions = [m for m in mentions if m.location == "title"]
        score = 0.0
        if title_mentions:
            first = min(m.start for m in title_mentions)
            score += self.rel["in_title"] + self.rel["title_position"] * (1 - first / max(1, len(doc.title)))
        else:
            score += self.rel["lead_only_base"]
        lead_sentences = split_sentences(doc.lead)
        if lead_sentences:
            surfaces = {m.surface for m in mentions if m.location != "hint"}
            hits = sum(any(s in sentence for s in surfaces) for sentence in lead_sentences)
            score += self.rel["lead_sentence_share"] * hits / len(lead_sentences)
        extra = len([m for m in mentions if m.location != "hint"]) - 1
        score += self.rel["repeat_mentions"] * min(max(extra, 0), 2) / 2
        if not title_mentions and not any(m.location == "lead" for m in mentions):
            score = min(score, self.rel["hint_only_cap"])  # hint-only links can never be the subject
        return min(1.0, score)
