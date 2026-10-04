from datetime import UTC, datetime

import pytest

from tripwire.models import Document
from tripwire.nlp.events import EventRules
from tripwire.nlp.frame import extract_frame, factuality
from tripwire.nlp.linking import EntityLinker
from tripwire.nlp.text import split_sentences, strip_filing_leakage
from tripwire.universe import load_universe


@pytest.fixture(scope="module")
def linker():
    return EntityLinker(load_universe())


@pytest.fixture(scope="module")
def rules():
    return EventRules()


def d(title, lead="", source="finnhub", hints=None):
    return Document(raw_id=1, dedup_key="k", source=source, source_type="news", title=title, lead=lead,
                    published_at=datetime(2026, 10, 1, tzinfo=UTC), hints=hints or {})


# ---------------------------------------------------------------- linking
def test_subject_of_headline_is_primary_with_high_confidence(linker):
    ents = linker.link(d("JPMorgan Chase posts record profit as Wells Fargo lags"))
    assert [e.ticker for e in ents][:2] == ["JPM", "WFC"]
    assert ents[0].link_confidence >= 0.95 and ents[0].relevance > ents[1].relevance


def test_ambiguous_alias_needs_corporate_context(linker):
    assert linker.link(d("Analysts raise price target on stocks")) == []          # lowercase 'target' never links
    weak = linker.link(d("Target practice: a guide for archers"))
    assert weak and weak[0].link_confidence == pytest.approx(0.60)                  # capitalised but no context
    strong = linker.link(d("Target shares slide after retailer cuts guidance"))
    assert strong[0].ticker == "TGT" and strong[0].link_confidence == pytest.approx(0.85)


def test_platform_mentions_are_weak_links(linker):
    # Real case: a court story about Facebook posts was linked to META with full confidence.
    [meta] = linker.link(d("Facebook posts revealed in judge 'bias' abuse appeal"))
    assert meta.link_confidence == pytest.approx(0.60)
    assert linker.link(d("Meta Platforms shares jump after earnings"))[0].link_confidence >= 0.95


def test_acronyms_are_case_sensitive(linker):
    assert linker.link(d("Markets saw ups and downs this week")) == []
    assert linker.link(d("UPS cuts 12,000 jobs"))[0].ticker == "UPS"


def test_filer_always_wins_and_is_fully_relevant(linker):
    doc = d("JPMORGAN CHASE & CO files 8-K: Item 2.02 Results", source="edgar", hints={"ticker": "JPM"})
    [jpm] = linker.link(doc)
    assert (jpm.link_confidence, jpm.relevance, jpm.method) == (1.0, 1.0, "filer")


def test_finnhub_related_hint_alone_is_nil(linker):
    # Observed in real data: a Home Depot story tagged WMT by Finnhub.
    ents = linker.link(d("How risky is Home Depot stock?", hints={"related": ["WMT"]}))
    assert [e.ticker for e in ents] == ["HD"]


def test_gdelt_boilerplate_org_hint_is_ignored_unless_named(linker):
    # Real case: GDELT tagged 'Google' on a road-safety page (share buttons), which linked it to GOOGL.
    page = d("Ontario highways add 110 km/h speed limits", source="gdelt", hints={"matched_tickers": ["GOOGL"]})
    assert linker.link(page) == []
    named = d("Google fined by EU regulators", source="gdelt", hints={"matched_tickers": ["GOOGL"]})
    assert linker.link(named)[0].ticker == "GOOGL"


def test_hint_only_link_is_never_the_subject(linker):
    # A non-boilerplate GDELT org hint without any text mention: linked, but not central.
    [jpm] = linker.link(d("Banks rally as yields fall", source="gdelt", hints={"matched_tickers": ["JPM"]}))
    assert jpm.relevance <= 0.30


def test_cashtags_and_lead_only_mentions(linker):
    ents = linker.link(d("Loading up on $BAC today", lead="Also watching Citigroup closely."))
    assert ents[0].ticker == "BAC" and ents[0].method == "cashtag"
    citi = next(e for e in ents if e.ticker == "C")
    assert not citi.in_title and citi.relevance < ents[0].relevance


# ---------------------------------------------------------------- text
def test_strip_filing_leakage_removes_item_headings_and_cover():
    text = ("UNITED STATES SECURITIES AND EXCHANGE COMMISSION Washington, D.C. 20549 FORM 8-K CURRENT REPORT\n"
            "Item 2.02 Results of Operations and Financial Condition\nNet revenue fell 12% in the quarter.")
    cleaned = strip_filing_leakage(text)
    assert "Item 2.02" not in cleaned and "Results of Operations" not in cleaned
    assert "Net revenue fell 12%" in cleaned


def test_split_sentences():
    assert split_sentences("Shares fell 4%. Analysts cut targets.\nNew line here") == [
        "Shares fell 4%.", "Analysts cut targets.", "New line here"]


# ---------------------------------------------------------------- events
@pytest.mark.parametrize("title, expected", [
    ("Regional lender files for Chapter 11 bankruptcy protection", ("Credit Event", "bankruptcy")),
    ("Moody's downgrades Ford credit rating to junk", ("Credit Event", "rating_downgrade")),
    ("US imposes new sanctions on Russian banks", ("Geopolitical", "sanctions")),
    ("Fed holds rates steady, signals two cuts", ("Macroeconomic", "central_bank_decision")),
    ("Pfizer agrees to buy biotech for $10 billion", ("Merger/Acquisition", "deal")),
    ("Meta fined $1.3 billion by EU regulators", ("Regulatory/Legal", "litigation_or_enforcement")),
    ("Hurricane forces refinery shutdowns along Gulf Coast", ("Natural Disaster/Supply Chain", "disaster")),
    ("Nike beats estimates, raises guidance", ("Earnings", "results")),
    ("Boeing CEO steps down amid safety crisis", ("Management Change", "officer_change")),
    ("Apple unveils new iPhone", ("Product Launch", "launch")),
])
def test_rules(rules, title, expected):
    decision = rules.decide(rules.evidence(d(title)))
    assert (decision.event_type, decision.subtype) == expected


def test_8k_items_map_and_most_severe_item_wins(rules):
    doc = d("X files 8-K", source="edgar", hints={"items": ["2.02", "2.04", "9.01"]})
    decision = rules.decide(rules.evidence(doc, text=""))
    assert (decision.event_type, decision.source) == ("Credit Event", "8k_item:2.04")


def test_generic_8k_item_yields_to_specific_text_rule(rules):
    doc = d("X enters material agreement", source="edgar", hints={"items": ["1.01"]})
    decision = rules.decide(rules.evidence(doc, text="X agrees to acquire Y for $2 billion"))
    assert decision.event_type == "Merger/Acquisition"


def test_no_evidence_means_no_rule_decision(rules):
    assert rules.decide(rules.evidence(d("Company hosts annual investor day"))) is None


# ---------------------------------------------------------------- frame / factuality
@pytest.mark.parametrize("title, lead, label", [
    ("3 bank stocks to buy now", "", "opinion"),
    ("Is Tesla stock a buy after the selloff?", "", "opinion"),
    ("Company denies report it is exploring a sale", "", "denied"),
    ("Pfizer reportedly in talks to acquire biotech", "", "rumour"),
    ("Pfizer agrees to acquire biotech", "", "announced"),
    ("Regional lender files for bankruptcy", "", "confirmed"),
    ("Retailer posts loss", "People familiar said a sale could follow.", "rumour"),
    ("Earnings due in May for retailer", "", "confirmed"),
    ("Why Citi's strategist is still betting on stocks", "", "opinion"),
    ("Bank makes fresh call on quantum stock", "Shares could rise further, it said.", "confirmed"),
])
def test_factuality(title, lead, label):
    assert factuality(title, lead)[0] == label


def test_frame_slots():
    frame = extract_frame("Pfizer agrees to acquire Seagen for $43 billion, shares up 4.5%", "", "PFE")
    assert frame.actor == "PFE" and frame.target == "Seagen"
    assert frame.amounts == ["$43 billion"] and frame.percentages == ["4.5%"]
    assert frame.factuality == "announced"


@pytest.mark.parametrize("text", [
    "Monthly Charge-Off and Delinquency Metrics As of and for the month ended December 31, 2022",
    "On November 18, 2024, the Company issued and sold $1,150,000,000 aggregate principal amount of its 5.272% "
    "Fixed-to-Floating Rate Senior Notes due 2031",
    "as Joint Lead Arrangers and Joint Bookrunners ARTICLE I DEFINITIONS AND ACCOUNTING TERMS",
])
def test_routine_financing_disclosures_are_not_credit_events(text):
    rules = EventRules()
    decision = rules.decide(rules.evidence(d(text)))
    assert decision.event_type == "Other" and decision.source == "rule:routine_financing"


def test_a_real_default_still_wins_over_routine_financing_words():
    rules = EventRules()
    text = "The company missed an interest payment on its notes; the underwriting agreement is terminated"
    assert rules.decide(rules.evidence(d(text))).event_type == "Credit Event"


def test_a_specific_8k_item_beats_a_passing_mention_in_the_press_release(rules):
    doc = d("BANK OF AMERICA CORP files 8-K: Item 2.02 Results of Operations", "Net income rose; hurricane-related "
            "provisions were modest", source="edgar", hints={"items": ["2.02", "9.01"]})
    assert rules.decide(rules.evidence(doc)).event_type == "Earnings"
    doc = d("X files 8-K: Item 2.02", "The auditor expressed substantial doubt about our ability to continue as a "
            "going-concern", source="edgar", hints={"items": ["2.02"]})
    assert rules.decide(rules.evidence(doc)).event_type == "Credit Event"  # severe credit text still wins


def test_a_voluntary_listing_transfer_is_not_a_delisting(rules):
    doc = d("LINDE PLC files 8-K: Item 3.01", "Linde announced its intention to transfer the listing of its "
            "ordinary shares to Nasdaq", source="edgar", hints={"items": ["3.01"]})
    assert rules.decide(rules.evidence(doc)).event_type == "Other"


def test_conditional_warnings_are_opinion_not_fact():
    label, _ = factuality("Apollo's Slok warns of a 'bank run' if households start using stablecoins")
    assert label == "opinion"


def test_weighing_a_policy_is_a_rumour_not_a_fact():
    assert factuality("Trump weighed a diesel export ban")[0] == "rumour"


RULE_CASES = [
    # (rule id, text, should fire) -- negatives are real false matches found in gold-set error analysis
    ("default", "Windows 11 will back up settings by default on eligible company devices", False),
    ("default", "The developer defaulted on its dollar bonds after missing a coupon", True),
    ("downgrade", "Nike CEO warned employees to expect further job cuts next year as the company changes its "
                  "operating model", False),
    ("downgrade", "ExxonMobil (NYSE:XOM) Stock Rating Lowered by Wells Fargo & Company", False),
    ("downgrade", "Analysts at Wells Fargo cut their rating on Netflix", False),
    ("downgrade", "S&P 500 falls as the Fed cuts rates", False),
    ("downgrade", "Moody's downgrades the regional lender to junk", True),
    ("downgrade", "S&P cuts the carmaker's credit rating to BB+", True),
    ("operations", "cognitive load and memory recall dropped with LLM use", False),
    ("operations", "S3 Vectors supports metadata pre-filtering for higher recall on filtered searches", False),
    ("operations", "GM Recalls Silverado And Sierra Trucks For Airbag Defect", True),
    ("operations", "Walmart announced the recall of 4.4 million grill brushes due to an ingestion hazard", True),
    ("disaster", "Vibe coded apps are about to flood the Play Store", False),
    ("disaster", "Rankings.io Acquires Wildfire Video, Launches Rankings Video Marketing", False),
    ("disaster", "EMS broadens its offering across fencing and hurricane protection", False),
    ("disaster", "Neptune Makes Flood Insurance Ready for the AI Agent Era", False),
    ("disaster", "Toyota halted Thai operations until October 10 due to flooding", True),
    ("disaster", "Hurricane Melissa forces refinery shutdowns along the Gulf Coast", True),
    ("launch", "France unveils cost-cutting 2027 budget as borrowing costs rise", False),
    ("launch", "Nvidia unveils record $150 billion buyback increase", False),
    ("launch", "Ministry of Finance launches a new edition of Fidelis", False),
    ("launch", "UPS unveils UPS Secure Commerce for end-to-end protection against fraud", True),
    ("legal", "integrated tools that reduce costs, errors and investigation time", False),
    ("legal", "SEC investigation into the bank's trading desk widens", True),
    ("legal", "New Mexico asks judge to fine Meta up to $40 billion; seeks penalty of $40 billion", True),
]


@pytest.mark.parametrize("rule_id, text, fires", RULE_CASES)
def test_rules_need_context_not_just_a_keyword(rules, rule_id, text, fires):
    fired = {e.source.split(":", 1)[1] for e in rules.evidence(d(text)) if e.source.startswith("rule:")}
    assert (rule_id in fired) is fires


def test_a_decimal_point_does_not_end_the_sentence_for_rules(rules):
    fired = {e.source for e in rules.evidence(d("The developer defaulted on its $1.5 billion bonds"))}
    assert "rule:default" in fired


@pytest.mark.parametrize("text, fires", [
    ("Agencies reduce regulatory burden for community banks, increase eligibility for 18-month exam cycle", True),
    ("Agencies seek comment on proposed third-party risk management guidance", True),
    ("Federal Reserve Board announces approval of application by Peoples Bancorp Inc.", True),
    ("Federal Reserve Board announces termination of enforcement action", True),
    ("Regulators worry about the economy as markets slide", False),
])
def test_regulator_actions_are_regulatory(rules, text, fires):
    assert any(e.source == "rule:regulator_action" for e in rules.evidence(d(text))) is fires


def test_a_central_bank_rate_decision_stays_macroeconomic(rules):
    doc = d("Federal Reserve Board approves a 25 basis point rate cut as policy eases")
    assert rules.decide(rules.evidence(doc)).event_type == "Macroeconomic"


def test_rule_evidence_is_the_exact_source_text(rules):
    doc = d("Regional lender files for Chapter 11 bankruptcy protection after deposit flight")
    ev = next(e for e in rules.evidence(doc) if e.source == "rule:bankruptcy")
    assert ev.phrase.lower() in doc.title.lower() and ev.phrase in ev.context


@pytest.mark.parametrize("text, cls", [
    ("Sixteen trucking companies collapsed in under a month", "Credit Event"),
    ("The retailer entered administration after talks with lenders failed", "Credit Event"),
    ("Developer files for creditor protection in Canada", "Credit Event"),
    ("Sharp rise in business insolvencies in Switzerland: insolvencies rose 12%", "Credit Event"),
    ("France unveils cost-cutting 2027 budget as borrowing costs rise", "Macroeconomic"),
    ("Bailout package for Swiss electricity firms will not be extended", "Macroeconomic"),
    ("Rupee falls to a record low against the dollar", "Macroeconomic"),
])
def test_distress_and_macro_phrasing(rules, text, cls):
    assert rules.decide(rules.evidence(d(text))).event_type == cls


@pytest.mark.parametrize("text", [
    "The Trump administration announced new hiring rules",
    "Our administration team is growing",
    "Two firms failed to agree on a partnership",
])
def test_distress_rule_needs_real_distress(rules, text):
    assert not any(e.source == "rule:distress" for e in rules.evidence(d(text)))


@pytest.mark.parametrize("title", [
    "Top 3 EV Stocks To Watch In October 2026",
    "What Does Weaker Viewing Actually Cost Netflix Stock?",
    "PepsiCo vs. Keurig: Which Stock Stands Out in the Beverage Race?",
    "Morgan Stanley Resets Okta Stock Price Target For Rest of Year",
])
def test_question_and_ranking_headlines_are_other(rules, title):
    decision = rules.decide(rules.evidence(d(title, "Rising bond yields rise and tariffs hit the sector")))
    assert decision.event_type == "Other" and decision.source == "rule:opinion_headline"


def test_an_8k_item_beats_an_opinion_style_title(rules):
    doc = d("X files 8-K: Item 2.02 Results? ", source="edgar", hints={"items": ["2.02"]})
    assert rules.decide(rules.evidence(doc)).event_type == "Earnings"


@pytest.mark.parametrize("text, fires", [
    ("Apollo's Torsten Slok warns of a 'bank run' if households start using AI", False),
    ("The fastest bank run in US history; now an economist warns AI could trigger the next one", False),
    ("Regional lender hit by a bank run as depositors pull $42 billion", True),
    ("Bank faces deposit flight after losses", True),
])
def test_bank_run_needs_an_actual_run(rules, text, fires):
    assert any(e.source == "rule:bank_run" for e in rules.evidence(d(text))) is fires


def test_rule_exclude_and_title_scope():
    from tripwire.config import load_yaml

    cfg = {"item_map": {}, "rules": [
        {"id": "disaster", "class": "Natural Disaster/Supply Chain", "subtype": "disaster", "pattern": "wildfire",
         "exclude": "supreme court|lawsuit"},
        {"id": "macro_data", "class": "Macroeconomic", "subtype": "macro_data_surprise", "pattern": "inflation",
         "scope": "title"},
    ]}
    r = EventRules(cfg, load_yaml("taxonomy.yaml"))
    assert r.decide(r.evidence(d("Wildfire forces evacuations in Maui"))).event_type == "Natural Disaster/Supply Chain"
    assert r.decide(r.evidence(d("Supreme Court hears wildfire survivor's climate case"))) is None
    assert r.decide(r.evidence(d("Inflation cools to 2.4% in September"))).event_type == "Macroeconomic"
    assert r.decide(r.evidence(d("Weekly round-up", "Airlines, inflation, tourism and startups"))) is None
