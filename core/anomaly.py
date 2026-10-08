"""Lens 2: provider peer-group outliers (robust z + IsolationForest). Run: python -m core.anomaly"""
import argparse
import hashlib
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from core import ledger
from core import schema as S

RECENT_DAYS = 90
EM_HI = ["99214", "99215"]
PRIOR_N = 5  # pseudo-claims shrinking E/M share toward the peer pool rate
MIN_CLAIMS = 5  # fewer claims in a period => that period's ratio features are not scored
BASE = ["em_hi_share", "units_per_claim", "paid_per_member", "claims_per_day", "members_per_day", "new_member_ratio"]
FEATURES = [f"{b}_{w}" for w in ("full", "90d") for b in BASE]
LABELS = {
    "em_hi_share": "share of E/M billed at 99214/99215", "units_per_claim": "units per claim",
    "paid_per_member": "paid $ per member-month (PMPM)", "claims_per_day": "claims per active day",
    "members_per_day": "distinct members per active day", "new_member_ratio": "share of members first seen in last 90 days",
}
Z_CAP, MIN_PEERS, TOP_DRIVERS = 10.0, 20, 3
DRIVER_W = [0.6, 0.25, 0.15]  # top driver dominates: single-feature schemes (upcoding) must still score
W_STRENGTH, STRENGTH_TAU = 0.7, 3.0
ALERT_MIN = 0.55


def _period(c: pd.DataFrame, first_seen: pd.Series, ramp_end: pd.Series, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
    """Provider features over service dates in (lo, hi]. A member is "new" if first seen by the provider inside the
    window and after the provider's own 90-day ramp-up (so recently enrolled providers are not penalised)."""
    x = c[(c.service_date > lo) & (c.service_date <= hi)]
    g = x.groupby("provider_id")
    em = x[x.cpt.isin(S.EM_LEVELS)]
    pairs = x.drop_duplicates(["provider_id", "member_id"])
    thr = np.maximum(pairs.provider_id.map(ramp_end).values, np.datetime64(lo))
    is_new = pairs.set_index(["provider_id", "member_id"]).index.map(first_seen).values > thr
    f = pd.DataFrame({
        "n_claims": g.size(), "n_em": em.groupby("provider_id").size(),
        "n_em_hi": em[em.cpt.isin(EM_HI)].groupby("provider_id").size(),
        "units_per_claim": g.units.mean(), "paid": g.paid_amt.sum(), "members": g.member_id.nunique(),
        "claims_per_day": g.size() / g.service_date.nunique(),
        "members_per_day": x.groupby(["provider_id", "service_date"]).member_id.nunique().groupby("provider_id").mean(),
        "new_member_ratio": pd.Series(is_new, index=pairs.provider_id.values).groupby(level=0).mean(),
    })
    f[["n_em", "n_em_hi"]] = f[["n_em", "n_em_hi"]].fillna(0)
    mm = x.drop_duplicates(["provider_id", "member_id", "month"]).groupby("provider_id").size()
    f["member_months"] = mm
    f["paid_per_member"] = f.paid / mm  # PMPM: window-length neutral
    return f


def features(claims: pd.DataFrame, providers: pd.DataFrame, asof: pd.Timestamp = S.END) -> pd.DataFrame:
    """Provider features over the full window, the last 90 days before `asof`, and the provider's own
    first 90 days of billing ("base", used to discount deviations present from day one). No data after asof."""
    c = claims[claims.service_date <= asof].astype({"provider_id": str, "member_id": str, "cpt": str})
    c = c.assign(month=c.service_date.dt.to_period("M"))
    first_seen = c.groupby(["provider_id", "member_id"]).service_date.min()
    recent = asof - pd.Timedelta(days=RECENT_DAYS)
    ramp_end = c.groupby("provider_id").service_date.min() + pd.Timedelta(days=RECENT_DAYS)
    in_ramp = c.service_date < c.provider_id.map(ramp_end)
    base = c[in_ramp & (c.provider_id.map(ramp_end) <= recent)]
    out = providers[["provider_id", "specialty", "type"]].astype(str).set_index("provider_id")
    out["peer_group"] = out.specialty + "|" + out.type
    start = c.service_date.min() - pd.Timedelta(days=1)
    for w, x, lo in [("full", c, start), ("90d", c, recent), ("base", base, start)]:
        f = _period(x, first_seen, ramp_end, lo, asof).reindex(out.index)
        pool = f.groupby(out.peer_group).transform("sum")
        f["em_hi_share"] = (f.n_em_hi + PRIOR_N * pool.n_em_hi / pool.n_em) / (f.n_em + PRIOR_N)
        f.loc[f.n_em == 0, "em_hi_share"] = np.nan
        f.loc[~(f.n_claims >= MIN_CLAIMS), BASE[1:]] = np.nan
        out[[f"{b}_{w}" for b in BASE]] = f[BASE].values
        for k in ["n_claims", "paid", "members", "member_months"]:
            out[f"{k}_{w}"] = f[k]
    out = out.drop(columns="new_member_ratio_base")  # every member is new in a provider's first 90 days
    return out.reset_index()


def robust_z(f: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(x - peer median) / (1.4826 * MAD); scale floored at 10% of |median| so near-constant peers can't blow up.
    Returns (z, peer median, scale)."""
    g = f.groupby("peer_group")[cols]
    med = g.transform("median")
    mad = (f[cols] - med).abs().groupby(f.peer_group).transform("median")
    scale = np.maximum(1.4826 * mad, 0.1 * med.abs())
    z = ((f[cols] - med) / scale.where(scale > 0)).fillna(0).clip(-Z_CAP, Z_CAP)
    return z, med, scale


def unexplained_z(f: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """One-sided peer z against an expectation that keeps the provider's own day-one level:
    expected = peer median * L, L = max(1, provider baseline / peer baseline median), noise scale * L. Stable case-mix outliers
    (oncology, busy ER) are explained by their baseline; onsets and long-running deviations from peers are not.
    Returns (adjusted z in [0, cap], peer medians, expected values)."""
    base = [f"{b}_base" for b in BASE if f"{b}_base" in f]
    _, med, scale = robust_z(f, FEATURES + base)
    adj, exp = pd.DataFrame(index=f.index), pd.DataFrame(index=f.index)
    for col in FEATURES:
        b = col.rsplit("_", 1)[0] + "_base"
        lift = (f[b] / med[b]).where(med[b] > 0).clip(lower=1).fillna(1) if b in f else 1
        exp[col] = med[col] * lift
        adj[col] = ((f[col] - exp[col]) / (scale[col] * lift).where(scale[col] > 0)).fillna(0).clip(0, Z_CAP)
    return adj, med, exp


def _isolation(adj: pd.DataFrame, groups: pd.Series) -> pd.Series:
    """IsolationForest anomaly score in ~[0, 1] per peer group (all providers if a group has < MIN_PEERS)."""
    out = pd.Series(np.nan, index=adj.index)
    small = groups.map(groups.value_counts()) < MIN_PEERS
    parts = [(g, idx) for g, idx in adj.index[~small].groupby(groups[~small]).items()] + [("*", adj.index)]
    for g, idx in parts:
        model = IsolationForest(n_estimators=200, n_jobs=4, random_state=S.SEED).fit(adj.loc[idx].values)
        s = -model.score_samples(adj.loc[idx].values)
        target = idx if g != "*" else adj.index[small]
        out[target] = pd.Series(s, index=idx)[target]
    return ((out - 0.45) / 0.3).clip(0, 1)


def score(f: pd.DataFrame) -> pd.DataFrame:
    """Per-provider anomaly score in [0, 1] plus the top drivers."""
    adj, med, exp = unexplained_z(f)
    top = np.sort(adj.values, axis=1)[:, ::-1][:, :TOP_DRIVERS]
    strength = top @ np.array(DRIVER_W)
    iso = _isolation(adj, f.peer_group)
    out = f[["provider_id", "peer_group"]].copy()
    out["strength"], out["iso"] = strength.round(3), iso.round(3)
    out["score"] = (W_STRENGTH * (1 - np.exp(-strength / STRENGTH_TAU)) + (1 - W_STRENGTH) * iso).round(3)
    order = np.argsort(-adj.values, axis=1)[:, :TOP_DRIVERS]
    out["drivers"] = [[adj.columns[j] for j in row if adj.iat[i, j] > 0] for i, row in enumerate(order)]
    return out.join(adj.add_prefix("z_")).join(med.add_prefix("med_")[[f"med_{c}" for c in FEATURES]]) \
              .join(exp.add_prefix("exp_"))


def _claim_ids(c: pd.DataFrame, pid: str, driver: str, asof: pd.Timestamp) -> list[str]:
    x = c[c.provider_id == pid]
    if driver.endswith("_90d"):
        x = x[x.service_date > asof - pd.Timedelta(days=RECENT_DAYS)]
    if driver.startswith("em_hi_share"):
        x = x[x.cpt.isin(EM_HI)]
    return x.claim_id.tolist()


def to_alerts(sc: pd.DataFrame, f: pd.DataFrame, claims: pd.DataFrame, asof: pd.Timestamp = S.END) -> pd.DataFrame:
    """One alert per provider scoring >= ALERT_MIN; evidence = top drivers vs peer median."""
    c = claims[claims.service_date <= asof].astype({"provider_id": str, "claim_id": str, "cpt": str})
    c = c[c.provider_id.isin(sc.provider_id[sc.score >= ALERT_MIN])]
    fx = f.set_index("provider_id")
    rows = []
    for r in sc[sc.score >= ALERT_MIN].sort_values("score", ascending=False).itertuples():
        ev = []
        for d in r.drivers:
            b, w = d.rsplit("_", 1)
            exp, med = getattr(r, f"exp_{d}"), getattr(r, f"med_{d}")
            note = f"; own baseline {exp:.3g}" if exp > med * 1.001 else ""
            ev.append({"field": d, "value": f"{fx.at[r.provider_id, d]:.3g}",
                       "expected": f"{med:.3g} (peer median {r.peer_group}, {w}{note}); z=+{getattr(r, f'z_{d}'):.1f}",
                       "source": "anomaly"})
        excess = fx.at[r.provider_id, "paid_full"] - r.exp_paid_per_member_full * fx.at[r.provider_id, "member_months_full"]
        rows.append({
            "alert_id": f"AN-{r.provider_id}", "lens": "anomaly", "entity_type": "provider", "entity_id": r.provider_id,
            "claim_ids": _claim_ids(c, r.provider_id, r.drivers[0], asof), "code": f"AN:{r.drivers[0].rsplit('_', 1)[0]}",
            "severity": 2 + int(r.score >= 0.7) + int(r.score >= 0.85), "score": float(r.score),
            "dollars_at_risk": round(max(0.0, float(excess)), 2), "evidence": ev,
        })
    return pd.DataFrame(rows, columns=S.ALERT_COLUMNS)


def run_anomaly(claims: pd.DataFrame, providers: pd.DataFrame, asof: pd.Timestamp = S.END) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (alerts, per-provider scores)."""
    f = features(claims, providers, asof)
    sc = score(f)
    return to_alerts(sc, f, claims, asof), sc


def log_run(alerts: pd.DataFrame, sc: pd.DataFrame, runtime_s: float, db=None) -> None:
    ids = ",".join(sorted(alerts.alert_id))
    ledger.append("system:anomaly", "lens_run", {
        "lens": "anomaly", "n_providers_scored": len(sc), "n_alerts": len(alerts), "alert_min": ALERT_MIN,
        "n_claims": int(alerts.claim_ids.map(len).sum()), "dollars_at_risk": round(float(alerts.dollars_at_risk.sum()), 2),
        "params": {"if_n_estimators": 200, "seed": S.SEED, "recent_days": RECENT_DAYS, "z_cap": Z_CAP},
        "alerts_sha": hashlib.sha256(ids.encode()).hexdigest(), "runtime_s": round(runtime_s, 2),
    }, db)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-ledger", action="store_true", help="dev: start a fresh ledger before logging")
    if ap.parse_args().reset_ledger:
        ledger.reset()
    t0 = time.time()
    alerts, sc = run_anomaly(S.load("claims"), S.load("providers"))
    runtime = time.time() - t0
    alerts.to_parquet(S.OUT / "alerts_anomaly.parquet", index=False)
    log_run(alerts, sc, runtime)
    print(alerts.code.value_counts().to_string())
    print(f"{len(alerts)} alerts / {len(sc)} providers in {runtime:.1f}s; ledger verify = {ledger.verify()}")


if __name__ == "__main__":
    main()
