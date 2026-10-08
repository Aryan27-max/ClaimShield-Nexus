"""Provider x month-end snapshots for the predictive lens.
Features use ONLY data with service_date <= T (graph at the latest quarter end <= T, investigations closed < T);
labels look at (T, T+h]. Run: python -m core.snapshots"""
import time

import numpy as np
import pandas as pd

from core import graph
from core import schema as S

HORIZONS = [30, 60, 90]
FIRST_MONTH = 4
STRONG_DET_STRUCT, STRONG_ANOMALY = 0.6, 0.86
EM_HI = ["99214", "99215"]
EM_PRIOR_N, EM_PRIOR_RATE = 5, 0.35  # E/M high share shrunk toward the expected mix
MIN_Z_CLAIMS = 5
Z_COLS = ["em_hi_share_3m", "units_per_claim_3m", "pmpm_3m", "claims_per_day_3m", "new_member_ratio_3m"]
GRAPH_COLS = ["out_top1_share", "in_top1_share", "out_recent_top1_share", "ppr_pct", "member_jaccard_max",
              "reciprocal_partners", "cycles3", "shared_owner_n", "shared_address_n", "shared_bank_n", "community_density"]
OUTCOMES = ["confirmed", "unfounded", "education"]


def month_ends() -> pd.DatetimeIndex:
    return pd.date_range(S.START, S.END, freq="ME")


def _wide(df: pd.DataFrame, col: str | None, pids: pd.Index, periods: pd.PeriodIndex) -> pd.DataFrame:
    """providers x months cumulative sum of `col` (or row count)."""
    s = df.groupby(["provider_id", "month"], observed=True).size() if col is None else \
        df.groupby(["provider_id", "month"], observed=True)[col].sum()
    return s.unstack(fill_value=0).reindex(index=pids, columns=periods, fill_value=0).cumsum(axis=1)


def _win(cum: pd.DataFrame, j: int, k: int, shift: int = 0) -> np.ndarray:
    """Sum over the k months ending at month index j - shift."""
    hi = j - shift
    if hi < 0:
        return np.zeros(len(cum))
    lo = hi - k
    return cum.iloc[:, hi].values - (cum.iloc[:, lo].values if lo >= 0 else 0)


def _claim_panel(claims: pd.DataFrame, rule_alerts: pd.DataFrame, pids: pd.Index, periods: pd.PeriodIndex) -> dict:
    c = claims[["claim_id", "provider_id", "member_id", "service_date", "cpt", "units", "paid_amt"]].astype(
        {"claim_id": str, "provider_id": str, "member_id": str, "cpt": str})
    c["month"] = c.service_date.dt.to_period("M")
    c["em"], c["em_hi"] = c.cpt.str.startswith("9921").astype(int), c.cpt.isin(EM_HI).astype(int)
    first = c.groupby(["provider_id", "member_id"]).month.min().rename("month").reset_index()
    flagged = rule_alerts[["code", "claim_ids"]].explode("claim_ids").rename(columns={"claim_ids": "claim_id"})
    flagged = flagged.dropna().astype({"claim_id": str}).merge(c[["claim_id", "provider_id", "month"]])
    w = {k: _wide(c, col, pids, periods) for k, col in
         [("n", None), ("paid", "paid_amt"), ("units", "units"), ("em", "em"), ("em_hi", "em_hi")]}
    w["mm"] = _wide(c.drop_duplicates(["provider_id", "member_id", "month"]), None, pids, periods)
    w["days"] = _wide(c.drop_duplicates(["provider_id", "service_date"]), None, pids, periods)
    w["new"] = _wide(first, None, pids, periods)
    w["rule"] = _wide(flagged.drop_duplicates("claim_id"), None, pids, periods)
    w["rule_codes"] = sum((_wide(g, None, pids, periods) > 0).astype(int) for _, g in flagged.groupby("code"))
    if isinstance(w["rule_codes"], int):
        w["rule_codes"] = w["n"] * 0
    return w


def _robust_z(f: pd.DataFrame) -> pd.DataFrame:
    g = f.groupby(["T", "peer"], observed=True)
    for col in Z_COLS:
        med = g[col].transform("median")
        mad = (f[col] - med).abs().groupby([f["T"], f["peer"]], observed=True).transform("median")
        z = (f[col] - med) / (1.4826 * mad + 1e-6 + 0.05 * med.abs())
        f[f"z_{col}"] = np.where(f.n_3m >= MIN_Z_CLAIMS, z.clip(-10, 10), 0.0)
    f["z_max"] = f[[f"z_{c}" for c in Z_COLS]].max(axis=1)
    return f


def _graph_quarters(t: dict, ends: pd.DatetimeIndex) -> pd.DataFrame:
    qs = [q for q in pd.date_range(S.START, S.END, freq="QE") if q <= ends.max()]
    rows = []
    for q in qs:
        f, _ = graph.features(t["providers"], t["referrals"], t["claims"], t["investigations"], asof=q)
        f = f.assign(in_ring=f.ring_id.notna().astype(int), graph_asof=q)
        rows.append(f[["provider_id", "graph_asof", "in_ring"] + GRAPH_COLS])
    return pd.concat(rows, ignore_index=True)


def strong_events(alerts: pd.DataFrame, claims: pd.DataFrame) -> pd.DataFrame:
    """(provider_id, date) of claims behind STRONG alerts: det/struct score >= 0.6 or anomaly score >= 0.86."""
    thr = np.where(alerts.lens == "anomaly", STRONG_ANOMALY, STRONG_DET_STRUCT)
    a = alerts[alerts.score >= thr][["entity_type", "entity_id", "claim_ids"]].explode("claim_ids").dropna()
    c = claims[["claim_id", "provider_id", "service_date"]].astype({"claim_id": str, "provider_id": str})
    a = a.astype({"claim_ids": str}).merge(c, left_on="claim_ids", right_on="claim_id")
    pid = np.where(a.entity_type == "community", a.provider_id, a.entity_id)
    return pd.DataFrame({"provider_id": pid, "date": a.service_date}).drop_duplicates()


def labels(snap: pd.DataFrame, events: pd.DataFrame, investigations: pd.DataFrame) -> pd.DataFrame:
    """label_h = strong alert on claims serviced in (T, T+h] OR confirmed investigation opened in (T, T+h].
    bl_* = naive baseline inputs (strong flags in (T-90, T]); never model features."""
    inv = investigations[investigations.outcome == "confirmed"]
    ev = pd.concat([events.assign(kind="alert"),
                    pd.DataFrame({"provider_id": inv.provider_id.astype(str), "date": inv.opened, "kind": "inv"})])
    out = []
    for T, grp in snap.groupby("T"):
        lab = {}
        for h in HORIZONS:
            win = ev[(ev.date > T) & (ev.date <= T + pd.Timedelta(days=h))]
            lab[f"label_{h}"] = grp.provider_id.isin(set(win.provider_id)).astype(float) \
                if T + pd.Timedelta(days=h) <= S.END else np.nan
        al = ev[ev.kind == "alert"]
        recent = al[(al.date > T - pd.Timedelta(days=90)) & (al.date <= T)].provider_id.value_counts()
        ever = set(al[al.date <= T].provider_id)
        out.append(grp.assign(**lab, bl_strong_90d=grp.provider_id.map(recent).fillna(0).values,
                              bl_strong_ever=grp.provider_id.isin(ever).astype(int).values))
    return pd.concat(out, ignore_index=True)


def build(t: dict, rule_alerts: pd.DataFrame, all_alerts: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (provider, month-end T) from month FIRST_MONTH; labels added when all_alerts is given."""
    p = t["providers"].assign(provider_id=t["providers"].provider_id.astype(str)).set_index("provider_id")
    pids, ends = p.index, month_ends()
    periods = ends.to_period("M")
    w = _claim_panel(t["claims"], rule_alerts, pids, periods)
    inv = t["investigations"].astype({"provider_id": str})
    rows = []
    for j in range(FIRST_MONTH - 1, len(ends)):
        T = ends[j]
        n3, n_prior = _win(w["n"], j, 3), _win(w["n"], j, 3, 3)
        paid3, paid_prior = _win(w["paid"], j, 3), _win(w["paid"], j, 3, 3)
        mm3, em3 = _win(w["mm"], j, 3), _win(w["em"], j, 3)
        f = pd.DataFrame({
            "provider_id": pids, "T": T, "n_3m": n3, "paid_3m": paid3,
            "vol_trend": np.log1p(n3) - np.log1p(n_prior), "paid_trend": np.log1p(paid3) - np.log1p(paid_prior),
            "em_hi_share_3m": (_win(w["em_hi"], j, 3) + EM_PRIOR_N * EM_PRIOR_RATE) / (em3 + EM_PRIOR_N),
            "units_per_claim_3m": _win(w["units"], j, 3) / np.maximum(n3, 1),
            "pmpm_3m": paid3 / np.maximum(mm3, 1),
            "claims_per_day_3m": n3 / np.maximum(_win(w["days"], j, 3), 1),
            "new_member_ratio_3m": _win(w["new"], j, 3) / np.maximum(mm3, 1),
            "claims_cum": w["n"].iloc[:, j].values, "paid_cum": w["paid"].iloc[:, j].values,
            "rule_flags_3m": _win(w["rule"], j, 3), "rule_flags_cum": w["rule"].iloc[:, j].values,
            "rule_codes_cum": w["rule_codes"].iloc[:, j].values,
            "tenure_days": (T - p.enroll_date).dt.days.values,
            "type": p.type.astype(str).values, "specialty": p.specialty.astype(str).values,
        })
        closed = inv[inv.closed < T].groupby(["provider_id", "outcome"]).size().unstack(fill_value=0)
        for o in OUTCOMES:
            f[f"inv_{o}_before"] = f.provider_id.map(closed[o] if o in closed else pd.Series(dtype=float)).fillna(0).values
        rows.append(f[(f.tenure_days >= 0) & (f.claims_cum > 0)])
    snap = pd.concat(rows, ignore_index=True)
    snap["peer"] = snap.specialty + "|" + snap.type
    snap = _robust_z(snap)
    gq = _graph_quarters(t, ends).sort_values("graph_asof")
    snap = pd.merge_asof(snap.sort_values("T"), gq, left_on="T", right_on="graph_asof", by="provider_id")
    snap[["in_ring"] + GRAPH_COLS] = snap[["in_ring"] + GRAPH_COLS].fillna(0)
    for c in ["type", "specialty", "peer"]:
        snap[c] = snap[c].astype("category")
    if all_alerts is not None:
        snap = labels(snap, strong_events(all_alerts, t["claims"]), t["investigations"])
    return snap.sort_values(["T", "provider_id"]).reset_index(drop=True)


def main() -> None:
    t0 = time.time()
    t = {n: S.load(n) for n in ["claims", "providers", "referrals", "investigations"]}
    alerts = pd.concat([S.load(f"alerts_{n}") for n in ["rules", "anomaly", "graph"]], ignore_index=True)
    snap = build(t, alerts[alerts.lens == "rules"], alerts)
    snap.to_parquet(S.OUT / "snapshots.parquet", index=False)
    print(snap.shape, {h: snap[f"label_{h}"].mean().round(4) for h in HORIZONS}, f"{time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
