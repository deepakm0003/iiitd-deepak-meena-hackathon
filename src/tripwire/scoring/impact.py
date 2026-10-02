"""The Impact Score: seven explainable factors, a relevance gate, and a calibrated 1-10 scale.

    raw      = sum_f  w_f * factor_f                 factors in [0, 1], weights sum to 1
    adjusted = raw * (0.6 + 0.4 * relevance)          passing mentions cannot score high
    impact   = piecewise-linear map of the percentile of `adjusted` within the CALIBRATION corpus:
               p0-50 -> 1-3, p50-80 -> 3-5, p80-95 -> 5-7, p95-100 -> 7-10
    So "Impact >= 7" means "in the top 5% of calibration events". P(large move) comes from isotonic regression
    of the calibration events' large-move indicator on impact. No LLM is involved anywhere.

Everything here is fitted on the calibration period only and frozen into ImpactModel (saved as JSON with a
hash), which is then applied unchanged to the out-of-time test period and to live events.
"""

import bisect
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

FACTORS = ["S_severity", "M_sentiment_magnitude", "E_entity_importance", "N_novelty",
           "V_volume_corroboration", "Q_source_credibility", "H_historical_reaction"]
BANDS = [(0.0, 1.0), (0.5, 3.0), (0.8, 5.0), (0.95, 7.0), (1.0, 10.0)]  # (percentile, impact)
SHRINK_K = 20  # pseudo-events pulling small classes' H toward their expert prior
MIN_ANCHOR_N = 30  # event types with at least this many calibration events define the H scale
# A weight can only be learned for the part of a factor's range the data covers. Severity is learnable only if
# the calibration sample holds enough genuinely severe events (defaults, bankruptcies, sanctions); a 2023-25
# large-cap 8-K sample holds almost none, so a fitted S weight would say nothing about the severe tail.
TAIL_COVERAGE = {"S_severity": (0.80, 30)}  # factor: (tail threshold, minimum calibration events in the tail)


@dataclass
class ImpactModel:
    weights: dict[str, float]
    h_table: dict[str, float]                   # event_type -> H factor in [0, 1]
    calibration_adjusted: list[float]           # sorted adjusted scores of the calibration corpus
    isotonic: list[tuple[float, float]] = field(default_factory=list)  # (impact, P(large move)) knots
    gate_floor: float = 0.6
    gate_slope: float = 0.4
    weights_source: str = "expert"              # expert | fitted
    calibration_period: tuple[str, str] = ("", "")

    @property
    def config_hash(self) -> str:
        body = json.dumps({k: v for k, v in asdict(self).items() if k != "isotonic"}, sort_keys=True)
        return "sha256:" + hashlib.sha256(body.encode()).hexdigest()[:16]

    def raw(self, factors: dict[str, float]) -> float:
        return sum(self.weights[f] * factors[f] for f in FACTORS)

    def adjusted(self, factors: dict[str, float], relevance: float) -> float:
        return self.raw(factors) * (self.gate_floor + self.gate_slope * relevance)

    def percentile(self, adjusted: float) -> float:
        corpus = self.calibration_adjusted
        return bisect.bisect_right(corpus, adjusted) / len(corpus) if corpus else 0.5

    def impact(self, adjusted: float) -> float:
        q = self.percentile(adjusted)
        for (q0, v0), (q1, v1) in zip(BANDS, BANDS[1:], strict=False):
            if q <= q1:
                return round(v0 + (v1 - v0) * (q - q0) / (q1 - q0), 2)
        return 10.0

    def p_large_move(self, impact: float) -> float | None:
        if not self.isotonic:
            return None
        xs = [x for x, _ in self.isotonic]
        i = bisect.bisect_right(xs, impact) - 1
        return round(self.isotonic[max(0, i)][1], 4)

    def score(self, factors: dict[str, float], relevance: float) -> dict:
        adjusted = self.adjusted(factors, relevance)
        impact = self.impact(adjusted)
        contributions = {f: round(self.weights[f] * factors[f], 4) for f in FACTORS}
        return {
            "impact": impact,
            "raw": round(self.raw(factors), 4),
            "relevance_gate": round(self.gate_floor + self.gate_slope * relevance, 4),
            "adjusted": round(adjusted, 4),
            "percentile": round(100 * self.percentile(adjusted), 1),
            "factors": {f: round(factors[f], 4) for f in FACTORS},
            "contributions": contributions,
            "p_large_move": self.p_large_move(impact),
            "config_hash": self.config_hash,
        }

    def save(self, path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.calibration_adjusted = [round(v, 6) for v in self.calibration_adjusted]  # compact, stable on disk
        path.write_text(json.dumps({**asdict(self), "config_hash": self.config_hash}, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "ImpactModel":
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("config_hash", None)
        data["isotonic"] = [tuple(x) for x in data.get("isotonic", [])]
        data["calibration_period"] = tuple(data.get("calibration_period", ("", "")))
        return cls(**data)


# ------------------------------------------------------------------------------------------------------
def h_table(abs_scar_by_type: dict[str, list[float]], priors: dict[str, float] | None = None) -> dict[str, float]:
    """Factor H: historical market reaction per event type, in [0, 1].

    measured_t = min-max scaled median |SCAR| of type t (calibration events only)
    H_t        = (n_t * measured_t + K * prior_t) / (n_t + K)       Bayesian shrinkage toward the expert prior
    Types with plenty of data are data-driven; rare types (few large-cap bankruptcies or sanctions ever reach an
    8-K) lean on the expert severity prior instead of an uninformative average. Types never observed = prior.
    """
    priors = priors or {}
    observed = {t: _median(sorted(v)) for t, v in abs_scar_by_type.items() if v}
    if not observed:
        return {t: round(p, 4) for t, p in priors.items()} | {"__default__": 0.5}
    # The 0-1 scale is anchored on well-measured types only; a type with two lucky filings must not stretch it.
    anchors = [m for t, m in observed.items() if len(abs_scar_by_type[t]) >= MIN_ANCHOR_N] or list(observed.values())
    lo, hi = min(anchors), max(anchors)
    scale = (lambda x: min(1.0, max(0.0, (x - lo) / (hi - lo)))) if hi > lo else (lambda x: 0.5)
    table = {}
    for t in set(observed) | set(priors):
        n = len(abs_scar_by_type.get(t, []))
        prior = priors.get(t, 0.5)
        measured = scale(observed[t]) if t in observed else prior
        table[t] = (n * measured + SHRINK_K * prior) / (n + SHRINK_K)
    everything = sorted(v for values in abs_scar_by_type.values() for v in values)
    table["__default__"] = scale(_median(everything))
    return {k: round(v, 4) for k, v in table.items()}


def fit_weights(rows: list[dict[str, float]], target: list[float]) -> dict[str, float]:
    """Non-negative weights summing to 1 that best fit the RANK of the target from factor ranks (NNLS).

    Ranks make the fit robust to outlier returns and match the Spearman criterion used in validation.
    """
    import numpy as np
    from scipy.optimize import nnls

    # Explicit intercept column, dropped afterwards. Without it, a factor that is (nearly) constant in the
    # calibration data, e.g. credibility for single-source filings, gets weight only because it acts as an
    # intercept, not because it ranks anything.
    x = np.column_stack([_ranks([r[f] for r in rows]) - 0.5 for f in FACTORS] + [np.ones(len(rows))])
    y = _ranks(target) - 0.5
    solution, _ = nnls(np.column_stack([x[:, :-1], x[:, -1], -x[:, -1]]), y)  # intercept may take any sign
    w = solution[: len(FACTORS)]
    total = w.sum()
    w = w / total if total > 0 else np.full(len(FACTORS), 1 / len(FACTORS))
    return {f: round(float(v), 4) for f, v in zip(FACTORS, w, strict=True)}


def identifiable(rows: list[dict[str, float]], min_variation: float = 0.2,
                 tail: dict[str, tuple[float, int]] | None = None) -> dict[str, bool]:
    """A factor is identifiable from the calibration data if at least `min_variation` of rows differ from its
    most common value and, for factors in `tail`, at least n rows reach the tail threshold. Weights for
    non-identifiable factors cannot be learned from this data."""
    tail = TAIL_COVERAGE if tail is None else tail
    out = {}
    for f in FACTORS:
        values = [round(r[f], 3) for r in rows]
        mode_share = max(values.count(v) for v in set(values)) / len(values) if values else 1.0
        out[f] = (1 - mode_share) >= min_variation
        if f in tail:
            threshold, n_min = tail[f]
            out[f] = out[f] and sum(v >= threshold for v in values) >= n_min
    return out


def tail_counts(rows: list[dict[str, float]], tail: dict[str, tuple[float, int]] | None = None) -> dict[str, dict]:
    tail = TAIL_COVERAGE if tail is None else tail
    return {f: {"threshold": t, "required": n, "observed": sum(r[f] >= t for r in rows)} for f, (t, n) in tail.items()}


def blend_weights(expert: dict[str, float], fitted: dict[str, float], ident: dict[str, bool]) -> dict[str, float]:
    """Expert weight for factors the data cannot speak to; data-fitted proportions for the rest."""
    fixed = {f: expert[f] for f in FACTORS if not ident[f]}
    free_mass = 1.0 - sum(fixed.values())
    learned = {f: fitted[f] for f in FACTORS if ident[f]}
    total = sum(learned.values())
    out = dict(fixed)
    for f, w in learned.items():
        out[f] = free_mass * (w / total if total else 1 / max(1, len(learned)))
    return {f: round(out[f], 4) for f in FACTORS}


def fit_isotonic(impacts: list[float], large: list[bool]) -> list[tuple[float, float]]:
    from sklearn.isotonic import IsotonicRegression

    if len(set(large)) < 2:
        return []
    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(impacts, [float(x) for x in large])
    return [(round(float(x), 3), round(float(y), 4)) for x, y in zip(model.X_thresholds_, model.y_thresholds_,
                                                                    strict=True)]


def _ranks(values: list[float]):
    from scipy.stats import rankdata

    return rankdata(values) / len(values)


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    mid = n // 2
    return sorted_values[mid] if n % 2 else (sorted_values[mid - 1] + sorted_values[mid]) / 2


def volume_factor(n_docs: int, n_publishers: int) -> float:
    return 0.5 * min(1.0, math.log(1 + n_docs) / math.log(21)) + 0.5 * min(1.0, n_publishers / 5)


def confidence(p_event: float, sentiment: float, p_entity: float, corroboration: float) -> float:
    """0.30 event-class probability + 0.25 sentiment certainty + 0.20 link confidence + 0.25 corroboration."""
    p_sent = 0.5 + 0.5 * min(1.0, abs(sentiment))
    return round(0.30 * p_event + 0.25 * p_sent + 0.20 * p_entity + 0.25 * corroboration, 4)
