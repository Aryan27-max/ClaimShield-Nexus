"""Lens 4: LightGBM 30/60/90-day escalation models on provider snapshots, isotonic calibration, SHAP drivers.
Run: python -m core.predict (needs data/out/snapshots.parquet from core.snapshots)"""
import hashlib
import json
import pickle
import time
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from core import ledger
from core import schema as S
from core.snapshots import HORIZONS, Z_COLS, GRAPH_COLS

MODELS = S.ROOT / "models"
TEST_START, CAL_MONTHS = pd.Timestamp("2025-01-31"), 2  # test = T >= TEST_START; cal = last 2 embargoed months
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, num_threads=4, random_state=S.SEED, verbose=-1)
FEATURES = (["n_3m", "paid_3m", "vol_trend", "paid_trend", "claims_cum", "paid_cum", "rule_flags_3m", "rule_flags_cum",
             "rule_codes_cum", "tenure_days", "inv_confirmed_before", "inv_unfounded_before", "inv_education_before",
             "z_max", "in_ring", "type", "specialty"] + Z_COLS + [f"z_{c}" for c in Z_COLS] + GRAPH_COLS)
LABELS_EN = {
    "n_3m": "claims in the last 3 months", "paid_3m": "paid $ in the last 3 months",
    "vol_trend": "claim volume trend (3 months vs prior 3)", "paid_trend": "paid $ trend (3 months vs prior 3)",
    "claims_cum": "total claims to date", "paid_cum": "total paid $ to date",
    "rule_flags_3m": "rule-flagged claims in the last 3 months", "rule_flags_cum": "rule-flagged claims to date",
    "rule_codes_cum": "distinct billing rules broken to date", "tenure_days": "days since enrollment",
    "inv_confirmed_before": "past confirmed investigations", "inv_unfounded_before": "past unfounded investigations",
    "inv_education_before": "past education outcomes", "z_max": "largest peer-group deviation",
    "in_ring": "member of a shared owner/address/bank ring", "type": "provider type", "specialty": "specialty",
    "em_hi_share_3m": "share of E/M visits billed at level 4-5", "units_per_claim_3m": "units per claim",
    "pmpm_3m": "paid $ per member-month", "claims_per_day_3m": "claims per active day",
    "new_member_ratio_3m": "share of new members",
    "z_em_hi_share_3m": "E/M level 4-5 share vs peers", "z_units_per_claim_3m": "units per claim vs peers",
    "z_pmpm_3m": "paid per member-month vs peers", "z_claims_per_day_3m": "claims per day vs peers",
    "z_new_member_ratio_3m": "new-member share vs peers",
    "out_top1_share": "share of referrals sent to one provider", "in_top1_share": "share of referrals from one provider",
    "out_recent_top1_share": "recent referral concentration (180 d)", "ppr_pct": "network proximity to confirmed fraud",
    "member_jaccard_max": "member overlap with another provider", "reciprocal_partners": "reciprocal referral partners",
    "cycles3": "3-way referral loops", "shared_owner_n": "providers sharing the owner",
    "shared_address_n": "providers sharing the address", "shared_bank_n": "providers sharing the bank account",
    "community_density": "referral community density",
}


def split(snap: pd.DataFrame, h: int) -> dict:
    """Time split with an embargo: a fit/cal row is kept only if its label window (T, T+h] ends by the
    next split's first T, so no training label sees events inside the calibration or test period."""
    lab = snap.dropna(subset=[f"label_{h}"])
    ends = lab["T"] + pd.Timedelta(days=h)
    pre = lab[ends <= TEST_START]
    cal_ts = sorted(pre["T"].unique())[-CAL_MONTHS:]
    fit = pre[ends[pre.index] <= cal_ts[0]] if len(cal_ts) == CAL_MONTHS else pre.iloc[:0]
    if fit.empty or not (lab["T"] >= TEST_START).any():
        raise ValueError(f"h={h}: not enough snapshot history around {TEST_START.date()} for an embargoed "
                         f"fit / {CAL_MONTHS}-month calibration / test split")
    return {"fit": fit, "cal": pre[pre["T"].isin(cal_ts)], "test": lab[lab["T"] >= TEST_START]}


def precision_at_k(df: pd.DataFrame, score: str, label: str, k: int = 20) -> float:
    """Mean over snapshot months of precision in the top-k providers."""
    return float(df.groupby("T").apply(lambda g: g.nlargest(k, score)[label].mean(), include_groups=False).mean())


def metrics(df: pd.DataFrame, score: str, label: str) -> dict:
    y = df[label].values
    ok = 0 < y.sum() < len(y)
    return {"n": len(df), "base_rate": round(float(y.mean()), 4),
            "roc_auc": round(float(roc_auc_score(y, df[score])), 3) if ok else None,
            "pr_auc": round(float(average_precision_score(y, df[score])), 3) if ok else None,
            "p_at_20": round(precision_at_k(df, score, label), 3)}


def compare(model: lgb.LGBMClassifier, iso: IsotonicRegression, test: pd.DataFrame, h: int) -> list[dict]:
    """Model vs a naive persistence baseline (strong flag in the last 90 d) on all test rows and on new-onset rows
    (no strong flag before T, where the baseline is blind). New-onset uses raw scores: isotonic plateaus tie."""
    raw = model.predict_proba(test[FEATURES])[:, 1]
    t = test.assign(p=iso.predict(raw), raw=raw, bl=test.bl_strong_90d)
    new, y = t[t.bl_strong_ever == 0], f"label_{h}"
    return [{"h": h, "scorer": name, "n_pos": int(df[y].sum()), **metrics(df, sc, y)}
            for name, sc, df in [("model", "p", t), ("baseline", "bl", t), ("model new-onset", "raw", new),
                                 ("baseline new-onset", "bl", new)]]


def train(snap: pd.DataFrame, h: int) -> tuple[lgb.LGBMClassifier, IsotonicRegression, dict]:
    sp = split(snap, h)
    y = f"label_{h}"
    model = lgb.LGBMClassifier(**PARAMS).fit(sp["fit"][FEATURES], sp["fit"][y])
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
        model.predict_proba(sp["cal"][FEATURES])[:, 1], sp["cal"][y])
    test = sp["test"].assign(p=iso.predict(model.predict_proba(sp["test"][FEATURES])[:, 1]))
    ranges = {k: [str(v["T"].min().date()), str(v["T"].max().date())] for k, v in sp.items()}
    return model, iso, {"ranges": ranges, "test": metrics(test, "p", y), "n_pos_fit": int(sp["fit"][y].sum()),
                        "comparison": compare(model, iso, sp["test"], h)}


def drivers(model: lgb.LGBMClassifier, X: pd.DataFrame, k: int = 3) -> list[list[dict]]:
    """Top-k features pushing risk UP for each row (TreeExplainer), in plain English."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        sv = shap.TreeExplainer(model.booster_).shap_values(X)
    sv = sv[1] if isinstance(sv, list) else sv
    out = []
    for i in range(len(X)):
        top = [j for j in np.argsort(-sv[i])[:k] if sv[i, j] > 0]
        out.append([{"feature": FEATURES[j], "label": LABELS_EN.get(FEATURES[j], FEATURES[j]),
                     "value": _fmt(X.iat[i, j]), "shap": round(float(sv[i, j]), 3)} for j in top])
    return out


def _fmt(v) -> str:
    return f"{v:,.2f}" if isinstance(v, (float, np.floating)) and not float(v).is_integer() else str(v)


def params_hash() -> str:
    return hashlib.sha256(json.dumps({"params": PARAMS, "features": FEATURES, "test_start": str(TEST_START),
                                      "cal_months": CAL_MONTHS, "embargo": "T+h <= next split start"}, sort_keys=True).encode()).hexdigest()


def run_predict(snap: pd.DataFrame, save: bool = True) -> tuple[pd.DataFrame, dict]:
    """Trains one model per horizon; returns (predictions for the latest snapshot, metrics)."""
    latest = snap[snap["T"] == snap["T"].max()].reset_index(drop=True)
    preds, report = [], {}
    MODELS.mkdir(exist_ok=True)
    for h in HORIZONS:
        model, iso, rep = train(snap, h)
        report[h] = rep
        p = iso.predict(model.predict_proba(latest[FEATURES])[:, 1])
        preds.append(pd.DataFrame({"provider_id": latest.provider_id.astype(str), "h": h, "T": latest["T"],
                                   "p_fwa": np.round(p, 4), "drivers": drivers(model, latest[FEATURES])}))
        if save:
            model.booster_.save_model(str(MODELS / f"lgbm_h{h}.txt"))
            (MODELS / f"iso_h{h}.pkl").write_bytes(pickle.dumps(iso))
    return pd.concat(preds, ignore_index=True), report


def log_run(report: dict, runtime_s: float, db=None) -> dict:
    return ledger.append("system:predict", "model_run", {
        "lens": "predict", "params_hash": params_hash(), "params": PARAMS, "n_features": len(FEATURES),
        "horizons": {str(h): r for h, r in report.items()}, "runtime_s": round(runtime_s, 2)}, db)


def main() -> None:
    t0 = time.time()
    preds, report = run_predict(pd.read_parquet(S.OUT / "snapshots.parquet"))
    runtime = time.time() - t0
    preds.to_parquet(S.OUT / "predictions.parquet", index=False)
    log_run(report, runtime)
    for h, r in report.items():
        print(h, r["ranges"], r["test"])
    print(f"trained 3 horizons in {runtime:.1f}s")


if __name__ == "__main__":
    main()
