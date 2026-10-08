"""Lens 1: deterministic claim edits (R01-R07) -> common alert schema. Run: python -m core.rules"""
import hashlib
import time

import numpy as np
import pandas as pd

from core import ledger
from core import schema as S

MAX_EVIDENCE = 25
META = {  # code: (name, severity, scheme it targets)
    "R01": ("duplicate claim", 3, "duplicate_billing"),
    "R02": ("NCCI unbundling", 2, "unbundling"),
    "R03": ("MUE units exceeded", 3, "excessive_units"),
    "R04": ("impossible daily time", 4, "impossible_timing"),
    "R05": ("service after date of death", 5, "phantom_services"),
    "R06": ("member geographically impossible same day", 4, "phantom_services"),
    "R07": ("excluded provider billing", 5, None),
}
BYPASS_MODIFIERS = {"59", "XS", "XU"}
DAY_KEY = ["member_id", "provider_id", "service_date"]


def _strs(v, n: int) -> np.ndarray:
    return np.full(n, str(v), dtype=object) if np.isscalar(v) else pd.Series(v).astype(str).values


def _hits(df: pd.DataFrame, code: str, field: str, value, expected, dollars) -> pd.DataFrame:
    """Claim-level rule hits: one evidence row per flagged claim."""
    return pd.DataFrame({
        "claim_id": df.claim_id.values, "provider_id": df.provider_id.values, "code": code, "field": field,
        "value": _strs(value, len(df)), "expected": _strs(expected, len(df)),
        "dollars": np.asarray(dollars, dtype=float),
    })


def _date(s: pd.Series) -> pd.Series:
    return s.dt.strftime("%Y-%m-%d")


def _km(lat1, lon1, lat2, lon2) -> np.ndarray:
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def r01_duplicates(c: pd.DataFrame) -> pd.DataFrame:
    key = DAY_KEY + ["cpt", "units"]
    s = c.sort_values(["submit_date", "claim_id"])
    dup = s.duplicated(key, keep="first")
    orig = s.groupby(key, observed=True).claim_id.transform("first")
    d = s[dup]
    value = d.member_id + " " + d.cpt + " " + _date(d.service_date) + " x" + d.units.astype(str)
    return _hits(d, "R01", "member_id|cpt|service_date|units", value, "unique; duplicate of " + orig[dup], d.paid_amt)


def r02_unbundling(c: pd.DataFrame) -> pd.DataFrame:
    out = []
    for c1, c2 in S.NCCI_PAIRS:
        col1 = c.loc[c.cpt == c1, DAY_KEY + ["claim_id"]].drop_duplicates(DAY_KEY)
        m = c[(c.cpt == c2) & ~c.modifier.isin(BYPASS_MODIFIERS)].merge(
            col1.rename(columns={"claim_id": "col1_claim"}), on=DAY_KEY)
        out.append(_hits(m, "R02", "cpt", m.cpt, f"bundled into {c1} same day (claim " + m.col1_claim + ")", m.paid_amt))
    return pd.concat(out, ignore_index=True)


def r03_mue(c: pd.DataFrame) -> pd.DataFrame:
    mue = c.cpt.map(S.cpt_table().mue)
    m = c.units > mue
    d, mue = c[m], mue[m]
    return _hits(d, "R03", "units", d.units, "<= " + mue.astype(int).astype(str) + " (MUE " + d.cpt + ")",
                 d.paid_amt * (d.units - mue) / d.units)


def r04_timing(c: pd.DataFrame, providers: pd.DataFrame) -> pd.DataFrame:
    timed = providers.provider_id[providers.type.isin(S.TIMED_PROVIDER_TYPES)]
    t = c[c.provider_id.isin(timed)].copy()
    t["day_min"] = t.groupby(["provider_id", "service_date"]).minutes.transform("sum")
    d = t[t.day_min > S.MAX_MINUTES_PER_DAY]
    value = d.day_min.astype(str) + " min billed on " + _date(d.service_date)
    excess = (d.day_min - S.MAX_MINUTES_PER_DAY) / d.day_min
    return _hits(d, "R04", "minutes_per_day", value, f"<= {S.MAX_MINUTES_PER_DAY} min", d.paid_amt * excess)


def r05_after_death(c: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    dod = c.member_id.map(members.set_index("member_id").dod)
    m = c.service_date > dod
    d = c[m]
    return _hits(d, "R05", "service_date", _date(d.service_date), "<= date of death " + _date(dod[m]), d.paid_amt)


def r06_geo(c: pd.DataFrame, members: pd.DataFrame, providers: pd.DataFrame, addresses: pd.DataFrame) -> pd.DataFrame:
    loc = providers[["provider_id", "address_id"]].merge(addresses[["address_id", "lat", "lon"]]).set_index("provider_id")
    home = members.set_index("member_id")
    x = c[["claim_id", "member_id", "provider_id", "service_date", "paid_amt"]].copy()
    x = x[x.groupby(["member_id", "service_date"]).provider_id.transform("nunique") > 1]
    x["lat"], x["lon"] = x.provider_id.map(loc.lat), x.provider_id.map(loc.lon)
    x["home_km"] = _km(x.lat, x.lon, x.member_id.map(home.lat), x.member_id.map(home.lon))
    p = x.merge(x, on=["member_id", "service_date"], suffixes=("", "_o"))
    p = p[p.provider_id != p.provider_id_o]
    p["km"] = _km(p.lat, p.lon, p.lat_o, p.lon_o)
    p = p[(p.km > S.GEO_IMPOSSIBLE_KM) & (p.home_km > p.home_km_o)]
    p = p.sort_values("km", ascending=False).drop_duplicates("claim_id")
    value = p.km.round().astype(int).astype(str) + " km from claim " + p.claim_id_o + " same day"
    return _hits(p, "R06", "provider_distance_km", value, f"<= {S.GEO_IMPOSSIBLE_KM} km", p.paid_amt)


def r07_excluded(c: pd.DataFrame, providers: pd.DataFrame) -> pd.DataFrame:
    d = c[c.provider_id.isin(providers.provider_id[providers.excluded_flag])]
    return _hits(d, "R07", "excluded_flag", "True", "False (provider not excluded)", d.paid_amt)


def to_alerts(hits: pd.DataFrame) -> pd.DataFrame:
    """Collapse claim-level hits into one alert per (rule, provider)."""
    rows = []
    for (code, pid), g in hits.groupby(["code", "provider_id"], sort=True):
        ids = list(dict.fromkeys(g.claim_id))
        ev = g.head(MAX_EVIDENCE)
        rows.append({
            "alert_id": f"{code}-{pid}", "lens": "rules", "entity_type": "provider", "entity_id": pid,
            "claim_ids": ids, "code": code, "severity": META[code][1],
            "score": round(1 - float(np.exp(-len(ids) / 5)), 3), "dollars_at_risk": round(g.dollars.sum(), 2),
            "evidence": [{"claim_id": r.claim_id, "field": r.field, "value": r.value, "expected": r.expected,
                          "source": f"rules:{code}"} for r in ev.itertuples()],
        })
    return pd.DataFrame(rows, columns=S.ALERT_COLUMNS)


def run_rules(claims: pd.DataFrame, members: pd.DataFrame, providers: pd.DataFrame,
              addresses: pd.DataFrame) -> pd.DataFrame:
    c = claims.astype({k: str for k in ["claim_id", "member_id", "provider_id", "cpt", "modifier"]})
    hits = pd.concat([
        r01_duplicates(c), r02_unbundling(c), r03_mue(c), r04_timing(c, providers),
        r05_after_death(c, members), r06_geo(c, members, providers, addresses), r07_excluded(c, providers),
    ], ignore_index=True)
    return to_alerts(hits)


def log_run(alerts: pd.DataFrame, runtime_s: float, db=None) -> None:
    """One ledger entry per rule: what fired, on how many claims, and a hash of the alert ids."""
    for code, (name, sev, _) in META.items():
        a = alerts[alerts.code == code]
        ids = ",".join(sorted(a.alert_id))
        ledger.append("system:rules", "rule_run", {
            "rule": code, "name": name, "severity": sev, "n_alerts": len(a),
            "n_claims": int(a.claim_ids.map(len).sum()), "dollars_at_risk": round(float(a.dollars_at_risk.sum()), 2),
            "alerts_sha": hashlib.sha256(ids.encode()).hexdigest(), "runtime_s": round(runtime_s, 2),
        }, db)


def summary(alerts: pd.DataFrame) -> pd.DataFrame:
    return alerts.assign(n_claims=alerts.claim_ids.map(len)).groupby("code").agg(
        alerts=("alert_id", "size"), claims=("n_claims", "sum"), dollars=("dollars_at_risk", "sum")).round(0)


def main() -> None:
    t0 = time.time()
    t = {n: S.load(n) for n in ["claims", "members", "providers", "addresses"]}
    alerts = run_rules(t["claims"], t["members"], t["providers"], t["addresses"])
    runtime = time.time() - t0
    alerts.to_parquet(S.OUT / "alerts_rules.parquet", index=False)
    log_run(alerts, runtime)
    print(summary(alerts).to_string())
    print(f"{len(alerts)} alerts in {runtime:.1f}s; ledger verify = {ledger.verify()}")


if __name__ == "__main__":
    main()
