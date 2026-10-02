from datetime import UTC, date, datetime, timedelta

import pytest

from tripwire.scoring.event_study import drop_confounded, market_model, reaction_day, returns, study

_ALL = [date(2025, 1, 1) + timedelta(days=i) for i in range(600)]
DAYS = [d for d in _ALL if d.weekday() < 5]


def test_reaction_day_respects_the_close():
    friday = date(2025, 3, 7)
    assert reaction_day(datetime(2025, 3, 7, 14, 0, tzinfo=UTC), DAYS) == friday          # 09:00 NY: same day
    assert reaction_day(datetime(2025, 3, 7, 21, 30, tzinfo=UTC), DAYS) == date(2025, 3, 10)  # 16:30 NY: Monday
    assert reaction_day(datetime(2025, 3, 8, 15, 0, tzinfo=UTC), DAYS) == date(2025, 3, 10)  # Saturday: Monday


def test_market_model_recovers_beta():
    import random

    rng = random.Random(1)
    m = {d: rng.gauss(0, 0.01) for d in DAYS}
    s = {d: 0.0002 + 1.5 * m[d] + rng.gauss(0, 0.002) for d in DAYS}
    alpha, beta, sigma, n = market_model(s, m, DAYS)
    assert beta == pytest.approx(1.5, abs=0.05) and sigma == pytest.approx(0.002, rel=0.2) and n == len(DAYS)


def test_confounded_events_are_dropped():
    events = [("a", "JPM", DAYS[200]), ("b", "JPM", DAYS[201]), ("c", "JPM", DAYS[260]), ("d", "BAC", DAYS[200])]
    kept, dropped = drop_confounded(events, DAYS)
    assert [k for k, _, _ in kept] == ["c", "d"] and dropped == 2


def test_study_detects_an_injected_abnormal_move():
    import random

    rng = random.Random(2)
    spy, stock = {}, {}
    p_m, p_s = 100.0, 50.0
    shock_day = DAYS[300]
    for d in DAYS:
        r_m = rng.gauss(0, 0.01)
        r_s = 1.2 * r_m + rng.gauss(0, 0.01) + (-0.08 if d == shock_day else 0.0)
        p_m *= 1 + r_m
        p_s *= 1 + r_s
        spy[d], stock[d] = p_m, p_s
    ts = datetime.combine(shock_day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=13)  # 08:00/09:00 NY
    quiet = datetime.combine(DAYS[330], datetime.min.time(), tzinfo=UTC) + timedelta(hours=13)
    out, stats = study([("shock", "X", ts), ("quiet", "X", quiet)], {"SPY": spy, "X": stock})
    by_key = {r.event_key: r for r in out}
    assert by_key["shock"].large and by_key["shock"].scar < -3
    assert not by_key["quiet"].large
    assert stats["studied"] == 2 and returns({DAYS[0]: 1.0, DAYS[1]: 1.1})[DAYS[1]] == pytest.approx(0.1)
