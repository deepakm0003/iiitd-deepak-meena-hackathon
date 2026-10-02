import pytest

from tripwire.scoring.impact import FACTORS, ImpactModel, confidence, fit_weights, h_table, volume_factor

EXPERT = dict(zip(FACTORS, [0.25, 0.15, 0.15, 0.10, 0.10, 0.10, 0.15], strict=True))


def model(corpus=None):
    corpus = corpus if corpus is not None else [i / 100 for i in range(100)]
    return ImpactModel(weights=EXPERT, h_table={}, calibration_adjusted=sorted(corpus))


def factors(v):
    return dict.fromkeys(FACTORS, v)


def test_weights_sum_to_one_and_all_ones_give_raw_one():
    m = model()
    assert sum(m.weights.values()) == pytest.approx(1.0)
    assert m.raw(factors(1.0)) == pytest.approx(1.0)


def test_raising_any_factor_never_lowers_impact():
    m = model()
    base = factors(0.4)
    for f in FACTORS:
        higher = {**base, f: 0.9}
        assert m.impact(m.adjusted(higher, 1.0)) >= m.impact(m.adjusted(base, 1.0))


def test_relevance_gate_lowers_score_for_passing_mentions():
    m = model()
    assert m.adjusted(factors(0.8), 0.1) < m.adjusted(factors(0.8), 1.0)
    assert m.score(factors(0.8), 0.1)["relevance_gate"] == pytest.approx(0.64)


def test_percentile_bands():
    m = model()
    assert m.impact(-1) == pytest.approx(1.0)
    assert m.impact(0.495) == pytest.approx(3.0)        # 50th percentile -> 3
    assert m.impact(0.795) == pytest.approx(5.0)        # 80th -> 5
    assert m.impact(0.945) == pytest.approx(7.0)        # 95th -> 7: "Impact 7 = top 5% of calibration events"
    assert m.impact(5.0) == pytest.approx(10.0)


def test_score_explains_itself_and_is_reproducible(tmp_path):
    m = model()
    s = m.score(factors(0.5), 1.0)
    assert sum(s["contributions"].values()) == pytest.approx(s["raw"], abs=1e-3)
    m.save(tmp_path / "m.json")
    again = ImpactModel.load(tmp_path / "m.json")
    assert again.config_hash == m.config_hash and again.score(factors(0.5), 1.0) == s


def test_h_table_is_data_driven_for_common_types_and_prior_driven_for_rare_ones():
    priors = {"Credit Event": 0.85, "Earnings": 0.5, "Other": 0.1, "Geopolitical": 0.8}
    table = h_table({"Credit Event": [0.5], "Earnings": [3.0] * 200, "Other": [0.5] * 200}, priors)
    # Earnings: 200 observations at the top of the measured scale -> close to 1
    assert table["Earnings"] == pytest.approx((200 * 1.0 + 20 * 0.5) / 220, abs=1e-3)
    # One quiet credit event cannot drag a rare, severe class to the bottom: it stays near its prior
    assert table["Credit Event"] == pytest.approx((1 * 0.0 + 20 * 0.85) / 21, abs=1e-3)
    assert table["Geopolitical"] == pytest.approx(0.8)  # never observed: the prior
    assert table["Other"] < 0.05 and "__default__" in table


def test_fit_weights_recovers_the_informative_factor():
    import random

    rng = random.Random(3)
    rows = [{f: rng.random() for f in FACTORS} for _ in range(400)]
    target = [r["M_sentiment_magnitude"] * 3 + rng.random() * 0.2 for r in rows]
    w = fit_weights(rows, target)
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-3) and all(v >= 0 for v in w.values())
    assert max(w, key=w.get) == "M_sentiment_magnitude"


def test_constant_factor_gets_no_weight():
    # Real case: credibility is ~1.0 for every single-source filing; it must not absorb the intercept.
    import random

    rng = random.Random(4)
    rows = [{**{f: rng.random() for f in FACTORS}, "Q_source_credibility": 1.0} for _ in range(400)]
    target = [r["H_historical_reaction"] + rng.random() * 0.3 for r in rows]
    w = fit_weights(rows, target)
    assert w["Q_source_credibility"] == 0.0 and max(w, key=w.get) == "H_historical_reaction"


def test_volume_and_confidence():
    assert volume_factor(1, 1) == pytest.approx(0.5 * 0.22767 + 0.1, abs=1e-3)
    assert volume_factor(100, 10) == pytest.approx(1.0)
    assert confidence(1.0, 1.0, 1.0, 1.0) == pytest.approx(1.0)


def test_blend_keeps_expert_weight_where_data_is_silent():
    from tripwire.scoring.impact import blend_weights, identifiable

    rows = [{**{f: i / 10 for f in FACTORS}, "Q_source_credibility": 1.0} for i in range(10)]
    ident = identifiable(rows)
    assert ident["Q_source_credibility"] is False and ident["H_historical_reaction"] is True
    fitted = {**dict.fromkeys(FACTORS, 0.0), "H_historical_reaction": 1.0}
    w = blend_weights(EXPERT, fitted, ident)
    assert w["Q_source_credibility"] == EXPERT["Q_source_credibility"]
    assert w["H_historical_reaction"] == pytest.approx(1 - EXPERT["Q_source_credibility"])
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-3)
