from datetime import UTC, datetime

from tripwire import gold
from tripwire.models import Document


def doc(i, title, source="finnhub"):
    return Document(raw_id=i, dedup_key=f"k{i}", source=source, source_type="news", title=title,
                    published_at=datetime(2026, 10, 1, tzinfo=UTC))


DOCS = [
    doc(1, "Bank files for Chapter 11 bankruptcy"),
    doc(2, "Bank files for Chapter 11 bankruptcy!"),      # same normalised title -> one item
    doc(3, "3 dividend stocks to buy now"),
    doc(4, "Retailer sued over data breach"),
    doc(5, "Apple unveils new phone"),
    doc(6, "Fed holds rates steady", source="fed"),
]


def test_source_quotas_stop_one_feed_crowding_out_others():
    docs = [doc(i, f"Finnhub story {i}") for i in range(100, 160)]
    docs += [doc(i, f"Filing {i}", source="edgar") for i in range(200, 205)]
    docs += [doc(i, f"Post {i}", source="bluesky") for i in range(300, 302)]
    rows = gold.sample_candidates(docs, n=20, quotas={"finnhub": 0.5, "edgar": 0.25, "bluesky": 0.25})
    by_source = {s: sum(r["source"] == s for r in rows) for s in ("finnhub", "edgar", "bluesky")}
    assert len(rows) == 20
    assert by_source["edgar"] == 5 and by_source["bluesky"] == 2   # all available; shortfall refilled
    assert by_source["finnhub"] == 13


def test_sampling_dedups_titles_boosts_rare_events_and_is_seeded():
    rows = gold.sample_candidates(DOCS, n=4, boost_share=0.5, seed=1, quotas={})
    assert len(rows) == 4
    titles = [r["title"].rstrip("!") for r in rows]
    assert len(set(titles)) == 4
    assert {r["stratum"] for r in rows if "bankruptcy" in r["title"] or "sued" in r["title"]} == {"boosted"}
    assert rows == gold.sample_candidates(DOCS, n=4, boost_share=0.5, seed=1, quotas={})
    assert all(r["split"] in {"dev", "test"} and r["split"] == gold.split_for(r["key"]) for r in rows)


def test_label_loop_saves_skips_undoes_and_quits(tmp_path):
    candidates = gold.sample_candidates(DOCS, n=5, seed=3, quotas={})
    answers = iter([
        "JPM", "1", "-", "c", "y", "bank run",   # item 1 saved
        "s",                                     # item 2 skipped
        "m", "3", "0", "o", "n", "",             # item 3 saved
        "b",                                     # undo item 3 -> shown again
        "m", "3", "+", "a", "n", "",             # item 3 saved again, corrected
        "zzz", "q",                              # invalid ticker then quit
    ])
    path = tmp_path / "gold.jsonl"
    saved = gold.label_loop(candidates, path, {"JPM"}, ask=lambda _: next(answers))
    rows = gold.read_jsonl(path)
    assert saved == 2 and len(rows) == 2
    assert rows[0]["entity"] == "JPM" and rows[0]["event_type"] == "Credit Event" and rows[0]["material"] is True
    assert rows[1]["entity"] == "MACRO" and rows[1]["sentiment"] == 1 and rows[1]["factuality"] == "announced"
    assert rows[1]["key"] == candidates[2]["key"]
    # Already-labelled items are not offered again.
    again = iter(["q"])
    gold.label_loop(candidates, path, {"JPM"}, ask=lambda _: next(again))
    assert len(gold.read_jsonl(path)) == 2


def test_stats():
    rows = [{"split": "test", "stratum": "random", "source": "fed", "event_type": "Macroeconomic",
             "factuality": "confirmed", "sentiment": 0, "material": True}]
    stats = gold.gold_stats(rows)
    assert stats["n"] == 1 and stats["event_type"] == {"Macroeconomic": 1}


def test_stratified_sampling_covers_prediction_and_recall_strata():
    from tripwire.gold import candidate_report, sample_stratified

    docs, predicted = [], {}
    for i in range(60):
        cls = ["Credit Event", "Other", "Earnings"][i % 3]
        title = f"Bank {i} files for bankruptcy protection" if cls == "Credit Event" else f"Story {i} about markets"
        if cls == "Other" and i < 45:   # 15 missed credit events among 20 Other items
            title = f"Lender {i} in default on its bonds, says filing"   # missed credit events go to recall
        item = doc(i, title)
        docs.append(item)
        predicted[item.dedup_key] = cls
    plan = {"Credit Event": 5, "Other": 5, "Earnings": 5}
    rows = sample_stratified(docs, predicted, plan=plan, recall_per_class=3)
    strata = candidate_report(rows, plan)["by_stratum"]
    assert strata["pred:Credit Event"] == 5 and strata["pred:Other"] == 5
    assert strata["recall:Credit Event"] == 3
    recall_rows = [r for r in rows if r["stratum"] == "recall:Credit Event"]
    assert all(predicted[r["key"]] != "Credit Event" for r in recall_rows)
    assert all(r["stratum_population"] >= 3 for r in recall_rows)
    assert len({r["key"] for r in rows}) == len(rows)                          # no item twice


def test_candidates_are_not_grouped_by_predicted_class():
    from tripwire.gold import sample_stratified

    docs = [doc(i, f"Distinct story number {i} here") for i in range(80)]
    predicted = {d.dedup_key: ("Credit Event" if i < 40 else "Other") for i, d in enumerate(docs)}
    rows = sample_stratified(docs, predicted, plan={"Credit Event": 20, "Other": 20}, recall_per_class=0)
    first_half = [r["stratum"] for r in rows[:20]]
    assert 0 < first_half.count("pred:Credit Event") < 20
