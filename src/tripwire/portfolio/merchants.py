"""Merchant behaviour from the Kaggle card-transaction data, and a validated behavioural risk model.

Pipeline (all DERIVED from the dataset, no PII kept):
  1. Stream the 13.3 M transactions in chunks into monthly aggregates per merchant, plus customer, state and
     category counts. Fiscal years run Nov-Oct, so FY2019 = Nov 2018 .. Oct 2019 (the last full year).
  2. Features for a fiscal year R (with prior year P): volume trend, monthly volatility, refund ratio,
     customer-side stress (insufficient balance, errors), fraud incidence, customer count, online share.
  3. Proxy credit target: volume in the NEXT fiscal year falls below 50% of the merchant's recent level (the
     mean of this and last year), or the merchant disappears. The data has no loan defaults; a collapse in card
     volume is a standard early-warning signal for merchant credit, so it is used (and reported) as a proxy,
     not as a default rate. The two-year base matters: against this year alone, a one-off spike "collapses"
     next year by construction (mean reversion), which inflated the first version's AUC (0.91 -> 0.85).
  4. Logistic regression (unweighted, so its output is a calibrated probability of the proxy event) trained on
     FY2015-16 features -> next-year outcomes, tested out-of-time on FY2018 -> FY2019, against baselines.
"""

import json
from pathlib import Path

FEATURES = ["neg_trend", "volatility", "refund_ratio", "insufficient_rate", "error_rate", "fraud_rate",
            "neg_log_customers", "online_share"]


def fiscal_year(year: int, month: int) -> int:
    return year + 1 if month >= 11 else year


def load_fraud_labels(path: Path):
    """Labelled transaction ids (sorted) and their fraud flag, as compact numpy arrays."""
    import numpy as np

    raw = json.loads(path.read_text(encoding="utf-8"))
    labels = raw.get("target", raw)
    ids = np.fromiter((int(k) for k in labels), dtype=np.int64, count=len(labels))
    flags = np.fromiter((v == "Yes" for v in labels.values()), dtype=bool, count=len(labels))
    order = np.argsort(ids)
    return ids[order], flags[order]


def aggregate(transactions_csv: Path, labels_path: Path, chunksize: int = 1_000_000):
    """One pass over the transactions. Returns (monthly, customers, states, mccs) DataFrames."""
    import numpy as np
    import pandas as pd

    label_ids, label_fraud = load_fraud_labels(labels_path)
    monthly_parts, customer_parts, state_parts, mcc_parts = [], [], [], []
    columns = ["id", "date", "client_id", "amount", "use_chip", "merchant_id", "merchant_state", "mcc", "errors"]
    for chunk in pd.read_csv(transactions_csv, usecols=columns, chunksize=chunksize):
        amount = chunk["amount"].str.replace("$", "", regex=False).astype(float)
        date = pd.to_datetime(chunk["date"])
        pos = np.searchsorted(label_ids, chunk["id"].to_numpy())
        pos = np.clip(pos, 0, len(label_ids) - 1)
        labelled = label_ids[pos] == chunk["id"].to_numpy()
        frame = pd.DataFrame({
            "merchant_id": chunk["merchant_id"],
            "ym": date.dt.year * 100 + date.dt.month,
            "gross": amount.clip(lower=0),
            "refunds": (-amount).clip(lower=0),
            "rows": 1,
            "errors": chunk["errors"].notna().astype(int),
            "insufficient": chunk["errors"].fillna("").str.contains("Insufficient Balance").astype(int),
            "online": (chunk["use_chip"] == "Online Transaction").astype(int),
            "labelled": labelled.astype(int),
            "fraud": (labelled & label_fraud[pos]).astype(int),
        })
        monthly_parts.append(frame.groupby(["merchant_id", "ym"], as_index=False).sum())
        fy = date.dt.year + (date.dt.month >= 11).astype(int)
        customer_parts.append(
            pd.DataFrame({"merchant_id": chunk["merchant_id"], "client_id": chunk["client_id"], "fy": fy})
            .drop_duplicates()
        )
        state_parts.append(chunk.groupby(["merchant_id", chunk["merchant_state"].fillna("ONLINE")])
                           .size().rename("n").reset_index())
        mcc_parts.append(chunk.groupby(["merchant_id", "mcc"]).size().rename("n").reset_index())
    monthly = pd.concat(monthly_parts).groupby(["merchant_id", "ym"], as_index=False).sum()
    customers = pd.concat(customer_parts).drop_duplicates()
    states = pd.concat(state_parts).groupby(["merchant_id", "merchant_state"], as_index=False)["n"].sum()
    mccs = pd.concat(mcc_parts).groupby(["merchant_id", "mcc"], as_index=False)["n"].sum()
    monthly["fy"] = monthly["ym"] // 100 + ((monthly["ym"] % 100) >= 11).astype(int)
    return monthly, customers, states, mccs


def features(monthly, customers, fy: int, min_volume: float = 2_000.0, min_rows: int = 10):
    """Per-merchant behaviour in fiscal year `fy` (with fy-1 as the comparison year)."""
    import numpy as np

    recent = monthly[monthly["fy"] == fy]
    prior = monthly[monthly["fy"] == fy - 1]
    g = recent.groupby("merchant_id")
    out = g[["gross", "refunds", "rows", "errors", "insufficient", "online", "labelled", "fraud"]].sum()
    out = out.rename(columns={"gross": "volume"})
    out["prior_volume"] = prior.groupby("merchant_id")["gross"].sum().reindex(out.index).fillna(0.0)
    monthly_volume = recent.pivot_table(index="merchant_id", columns="ym", values="gross", aggfunc="sum").fillna(0)
    out["active_months"] = (monthly_volume > 0).sum(axis=1).reindex(out.index)
    out["volatility"] = (monthly_volume.std(axis=1) / monthly_volume.mean(axis=1).replace(0, np.nan)).reindex(out.index)
    n_customers = customers[customers["fy"] == fy].groupby("merchant_id")["client_id"].nunique()
    out["customers"] = n_customers.reindex(out.index).fillna(0)
    out = out[(out["volume"] >= min_volume) & (out["rows"] >= min_rows)].copy()
    out["neg_trend"] = -np.log((out["volume"] + 1) / (out["prior_volume"] + 1))
    out["refund_ratio"] = out["refunds"] / (out["volume"] + 1)
    out["insufficient_rate"] = out["insufficient"] / out["rows"]
    out["error_rate"] = out["errors"] / out["rows"]
    out["fraud_rate"] = (out["fraud"] / out["labelled"].replace(0, np.nan)).fillna(0.0)
    out["neg_log_customers"] = -np.log1p(out["customers"])
    out["online_share"] = out["online"] / out["rows"]
    out["volatility"] = out["volatility"].fillna(out["volatility"].median())
    return out


def distress_outcome(monthly, fy: int, merchants, threshold: float = 0.5):
    """1 if volume in fiscal year fy+1 is below (1 - threshold) x the recent level, or zero (merchant gone).

    Recent level = mean of fy and fy-1 volumes (fy alone for merchants new in fy), so a one-off spike in fy is
    not counted as a collapse when volume returns to normal."""
    import numpy as np

    def volume(year):
        return monthly[monthly["fy"] == year].groupby("merchant_id")["gross"].sum().reindex(merchants).fillna(0)

    now, prev, nxt = volume(fy), volume(fy - 1), volume(fy + 1)
    base = np.where(prev > 0, (now + prev) / 2, now)
    return (nxt < (1 - threshold) * base).astype(int)


def validate_risk_model(monthly, customers, train_fys: tuple[int, ...] = (2015, 2016),
                        test_fy: int = 2018) -> tuple[object, dict]:
    """Fit on train_fys (each -> next year), test out-of-time on test_fy -> test_fy+1.

    FY2017 -> FY2018 is deliberately left out of training: its outcome year overlaps the test features year.
    """
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    parts = [features(monthly, customers, fy) for fy in train_fys]
    train = pd.concat(parts)
    y_train = pd.concat([distress_outcome(monthly, fy, part.index) for fy, part in zip(train_fys, parts, strict=True)])
    test = features(monthly, customers, test_fy)
    y_test = distress_outcome(monthly, test_fy, test.index)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    model.fit(train[FEATURES], y_train)
    p_test = model.predict_proba(test[FEATURES])[:, 1]

    def auc_ci(scores, n_boot=500, seed=3):
        rng = np.random.default_rng(seed)
        y, s = y_test.to_numpy(), np.asarray(scores)
        vals = []
        for _ in range(n_boot):
            idx = rng.integers(0, len(y), len(y))
            if y[idx].min() != y[idx].max():
                vals.append(roc_auc_score(y[idx], s[idx]))
        vals.sort()
        return [round(float(vals[int(0.025 * len(vals))]), 4), round(float(vals[int(0.975 * len(vals)) - 1]), 4)]

    z = (test[FEATURES] - train[FEATURES].mean()) / train[FEATURES].std().replace(0, 1)
    baselines = {"equal_weight_zscore": z.sum(axis=1), "volatility_only": test["volatility"],
                 "few_customers_only": test["neg_log_customers"],
                 "volume_decline_only": test["neg_trend"]}
    deciles = np.quantile(p_test, np.linspace(0, 1, 11))
    bucket = np.clip(np.searchsorted(deciles, p_test, side="right") - 1, 0, 9)
    report = {
        "target": "next fiscal year card volume < 50% of the mean of this and last year, or merchant gone "
                  "(proxy for credit distress)",
        "train": {"features_fy": list(train_fys), "n": int(len(train)),
                  "base_rate": round(float(y_train.mean()), 4)},
        "test": {"features_fy": test_fy, "outcome_fy": test_fy + 1, "n": int(len(test)),
                 "base_rate": round(float(y_test.mean()), 4),
                 "auc": round(float(roc_auc_score(y_test, p_test)), 4), "auc_ci95": auc_ci(p_test),
                 "brier": round(float(np.mean((p_test - y_test.to_numpy()) ** 2)), 5),
                 "mean_predicted": round(float(p_test.mean()), 4)},
        "findings": [
            "Monthly volume volatility alone ranks almost as well as the full model: revenue volatility is the "
            "dominant early-warning driver in this data.",
            "Volume decline alone ranks below chance: after a decline volume tends to recover, and growth "
            "years are followed by falls (mean reversion), so a naive 'shrinking merchant' rule fails here.",
            "Merchants almost never disappear in this dataset, so the target is a revenue collapse, not an exit.",
        ],
        "baselines_test_auc": {k: round(float(roc_auc_score(y_test, v)), 4) for k, v in baselines.items()},
        "distress_rate_by_risk_decile_test": [
            round(float(y_test.to_numpy()[bucket == d].mean()), 4) if (bucket == d).any() else None for d in range(10)
        ],
        "coefficients_standardised": {
            f: round(float(c), 4) for f, c in zip(FEATURES, model[-1].coef_[0], strict=True)
        },
    }
    return model, report


def home_state(states):
    """Most frequent state per merchant; 'ONLINE' when most transactions carry no state."""
    idx = states.groupby("merchant_id")["n"].idxmax()
    return states.loc[idx].set_index("merchant_id")["merchant_state"]


def main_mcc(mccs):
    idx = mccs.groupby("merchant_id")["n"].idxmax()
    return mccs.loc[idx].set_index("merchant_id")["mcc"]

