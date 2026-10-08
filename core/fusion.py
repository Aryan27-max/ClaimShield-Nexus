"""Fusion: lens alerts -> entity cases (provider or ring) with evidence classes, fused confidence,
$ at risk, member harm and plain-language limitations."""
import numpy as np
import pandas as pd

from core import schema as S

CLASSES = ["deterministic", "structural", "statistical", "predictive"]
CLAIM_LEVEL = ("deterministic", "structural")
MAX_EVIDENCE_PER_ALERT, MAX_EVIDENCE = 10, 80


def load_alerts() -> pd.DataFrame:
    return pd.concat([S.load(f"alerts_{n}") for n in ["rules", "anomaly", "graph"]], ignore_index=True)


def ring_map(graph_features: pd.DataFrame) -> pd.Series:
    """provider_id -> ring_id for providers inside a detected ring."""
    gf = graph_features.dropna(subset=["ring_id"])
    return pd.Series(gf.ring_id.astype(str).values, index=gf.provider_id.astype(str).values)


def assign_cases(alerts: pd.DataFrame, rings: pd.Series, class_map: dict) -> pd.DataFrame:
    """Adds `cls` and `case_id`; provider alerts of ring members roll into the ring case."""
    a = alerts.copy()
    a["cls"] = a.lens.map(class_map)
    a["case_id"] = np.where(a.entity_type == "community", a.entity_id,
                            a.entity_id.map(rings).fillna(a.entity_id))
    return a


def provider_profile(t: dict, policy: dict) -> pd.DataFrame:
    """Per-provider history and data-completeness factor (penalties from policy)."""
    c = t["claims"]
    pid = c.provider_id.astype(str)
    g = c.groupby(pid, observed=True)
    prof = pd.DataFrame({"n_claims": g.size(), "first": g.service_date.min(), "last": g.service_date.max()})
    prof["active_days"] = (prof["last"] - prof["first"]).dt.days
    r = t["referrals"]
    refd = c.referring_provider_id.dropna()
    with_ref = set(r.from_provider.astype(str)) | set(r.to_provider.astype(str)) | set(refd.astype(str)) \
        | set(pid[c.referring_provider_id.notna()])
    prof["has_referrals"] = prof.index.isin(with_ref)
    p = t["providers"].set_index(t["providers"].provider_id.astype(str))
    prof = prof.reindex(p.index).fillna({"n_claims": 0, "active_days": 0, "has_referrals": False})
    prof["type"] = p.type.astype(str)
    cp = policy["completeness"]
    prof["short_history"] = prof.active_days < cp["min_active_days"]
    prof["sparse_history"] = prof.n_claims < cp["min_claims"]
    prof["completeness"] = np.where(prof.short_history, cp["short_history_factor"], 1.0) \
        * np.where(prof.sparse_history, cp["sparse_factor"], 1.0) * np.where(prof.has_referrals, 1.0, cp["no_referrals_factor"])
    return prof


def _union(ids: pd.Series) -> list[str]:
    return sorted({str(x) for lst in ids for x in lst})


def _evidence(grp: pd.DataFrame) -> list[dict]:
    out = []
    for r in grp.sort_values(["severity", "score"], ascending=False).itertuples():
        for e in list(r.evidence)[:MAX_EVIDENCE_PER_ALERT]:
            out.append({"claim_id": str(e.get("claim_id") or ""), "field": e["field"], "value": str(e["value"]),
                        "expected": str(e["expected"]), "lens": r.lens, "class": r.cls, "code": r.code,
                        "alert_id": r.alert_id, "entity_id": r.entity_id})
    return out[:MAX_EVIDENCE]


def _limitations(classes: set, codes: set, n_det_claims: int, prof: pd.DataFrame, is_ring: bool) -> list[str]:
    lim = []
    if classes == {"statistical"}:
        lim.append("Only statistical evidence (peer comparison); no rule or network corroboration.")
    elif len(classes) == 1:
        lim.append(f"Single evidence class ({next(iter(classes))}); no independent corroboration.")
    if "AN:em_hi_share" in codes and "deterministic" not in classes:
        lim.append("Upcoding detected by peer comparison only; medical records not reviewed.")
    if classes == {"deterministic"} and n_det_claims <= 5:
        lim.append(f"Rule hits on only {n_det_claims} claims; pattern may be clerical error.")
    n = len(prof)
    for col, text in [("short_history", "active < 90 days"), ("sparse_history", "with < 30 claims (sparse history)")]:
        k = int(prof[col].sum())
        if k:
            lim.append(f"Provider {text}." if n == 1 else f"{k} of {n} providers {text}.")
    k = int((~prof.has_referrals).sum())
    if k:
        lim.append("No referral data; network lens could not assess referral patterns." if n == 1
                   else f"{k} of {n} providers have no referral data.")
    if is_ring:
        lim.append(f"Ring case covering {n} providers; individual roles not yet established.")
    lim.append("Predictive lens not yet available; confidence uses fused evidence only.")
    return lim


def _case(cid: str, grp: pd.DataFrame, providers: list[str], t: dict, prof: pd.DataFrame, policy: dict) -> dict:
    w = policy["class_weights"]
    scores = grp.groupby("cls").score.max()
    fused = 1 - float(np.prod([1 - w[c] * s for c, s in scores.items()]))
    pp = prof.loc[providers]
    completeness = float(pp.completeness.mean())
    classes = set(scores.index)
    ids = {c: _union(grp.claim_ids[grp.cls == c]) for c in classes}
    paid, mem = t["paid"], t["claim_member"]
    claim_level = sorted(set().union(*[ids.get(c, []) for c in CLAIM_LEVEL]))
    by_class = {c: round(float(paid.reindex(ids[c]).sum()), 2) for c in CLAIM_LEVEL if c in ids}
    if "statistical" in classes:
        by_class["statistical"] = round(float(grp.dollars_at_risk[grp.cls == "statistical"].sum()), 2)
    dollars = float(paid.reindex(claim_level).sum()) if claim_level else by_class.get("statistical", 0.0)
    all_ids = sorted(set().union(*ids.values()))
    members = mem.reindex(all_ids).dropna().unique()
    age = t["member_age"].reindex(members)
    vuln = float(((age < 18) | (age >= 65)).mean()) if len(members) else 0.0
    mh = policy["member_harm"]
    type_w = max(mh["type_weights"].get(tp, mh["type_weights"]["default"]) for tp in pp.type)
    codes = sorted(set(grp.code))
    return {
        "case_id": cid, "case_type": "ring" if cid.startswith("RING-") else "provider",
        "providers": providers, "provider_types": sorted(set(pp.type)), "n_providers": len(providers),
        "classes": [c for c in CLASSES if c in classes], "n_classes": len(classes),
        **{f"score_{c}": round(float(scores.get(c, 0.0)), 3) for c in CLASSES},
        "evidence_strength": round(sum(w[c] for c in classes), 3),
        "fused_score": round(fused, 3), "completeness": round(completeness, 3),
        "confidence": round(fused * completeness, 3),
        "alert_ids": sorted(grp.alert_id), "codes": codes, "max_severity": int(grp.severity.max()),
        "flagged_claim_ids": all_ids, "n_flagged_claims": len(all_ids),
        "dollars_at_risk": round(dollars, 2),
        **{f"dollars_{c}": by_class.get(c, 0.0) for c in CLASSES[:3]},
        "members_affected": int(len(members)), "vulnerable_share": round(vuln, 3),
        "member_harm_w": round(type_w * (1 + mh["vulnerable_bonus"] * vuln), 3),
        "limitations": _limitations(classes, set(codes), len(ids.get("deterministic", [])), pp, cid.startswith("RING-")),
        "evidence": _evidence(grp),
    }


def build_cases(alerts: pd.DataFrame, t: dict, graph_features: pd.DataFrame, policy: dict) -> pd.DataFrame:
    """One row per case; `t` needs claims, providers, members, referrals."""
    rings = ring_map(graph_features)
    a = assign_cases(alerts, rings, policy["class_map"])
    prof = provider_profile(t, policy)
    c = t["claims"]
    cid = c.claim_id.astype(str)
    m = t["members"]
    ctx = {"paid": pd.Series(c.paid_amt.values, index=cid),
           "claim_member": pd.Series(c.member_id.astype(str).values, index=cid),
           "member_age": pd.Series(((S.END - m.dob).dt.days / 365.25).values, index=m.member_id.astype(str))}
    members_of = rings.groupby(rings.values).apply(lambda s: sorted(s.index)).to_dict()
    rows = [_case(k, grp, members_of.get(k, [k]), ctx, prof, policy) for k, grp in a.groupby("case_id", sort=True)]
    return pd.DataFrame(rows)


def funnel(alerts: pd.DataFrame, cases: pd.DataFrame) -> dict:
    """Alert-collapse funnel: flagged claims -> alerts -> cases."""
    return {"claims_flagged": len(_union(alerts.claim_ids)), "alerts": len(alerts), "cases": len(cases)}
