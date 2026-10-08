"""Graph lens alerts: concentrated referral flows (kickback) and community-level rings."""
import numpy as np
import pandas as pd

from core import schema as S

RECENT_DAYS = 180
KICKBACK_SHARE, MIN_REFERRALS = 0.8, 10  # spec: >80% of referrals to one entity
HARM_TYPES = {"dme", "home_health", "bh"}  # member-harm provider types => higher severity


def to_alerts(f: pd.DataFrame, ctx: dict, claims: pd.DataFrame, providers: pd.DataFrame,
              asof: pd.Timestamp = S.END) -> pd.DataFrame:
    """Provider alerts for concentrated referral flows (kickback) + community alerts for rings."""
    c = claims[claims.service_date <= asof].astype(
        {"claim_id": str, "provider_id": str, "member_id": str, "referring_provider_id": str})
    ptype = providers.set_index(providers.provider_id.astype(str)).type.astype(str)
    fx = f.set_index("provider_id")
    conc = fx[(fx.n_out_recent >= MIN_REFERRALS) & (fx.out_recent_top1_share >= KICKBACK_SHARE)]
    pairs = list(zip(conc.index, conc.out_recent_top1))
    rows = []

    def ev(field, value, expected):
        return {"field": field, "value": str(value), "expected": str(expected), "source": "graph"}

    def kick(pid, flows, evidence, harm):
        cl = c.merge(pd.DataFrame(flows, columns=["referring_provider_id", "provider_id"]))
        share = max(fx.at[a, "out_recent_top1_share"] for a, _ in flows)
        n = sum(fx.at[a, "n_out_recent"] for a, _ in flows)
        code = "G01" if flows[0][0] == pid else "G02"
        rows.append({"alert_id": f"GR-{code}-{pid}", "lens": "graph", "entity_type": "provider", "entity_id": pid,
                     "claim_ids": cl.claim_id.tolist(), "code": code,
                     "severity": 3 + harm, "score": round(float(share * (1 - np.exp(-n / 20))), 3),
                     "dollars_at_risk": round(float(cl.paid_amt.sum()), 2), "evidence": evidence})

    for a, b in pairs:
        r = fx.loc[a]
        kick(a, [(a, b)], [
            ev("out_recent_top1_share", f"{r.out_recent_top1_share:.2f} of {r.n_out_recent} referrals to {b}",
               f"<= {KICKBACK_SHARE} (last {RECENT_DAYS} days)"),
            ev("out_top1_share", f"{r.out_top1_share:.2f} (full window)", f"peer median {fx.out_top1_share.median():.2f}"),
            ev("member_jaccard_max", f"{r.member_jaccard_max:.2f} with {r.member_jaccard_with}", "< 0.05 typical")],
            int(ptype[b] in HARM_TYPES))
    for b, grp in pd.DataFrame(pairs, columns=["a", "b"]).groupby("b"):
        r = fx.loc[b]
        evs = [ev("inbound_flow", f"{fx.at[a, 'out_recent_top1_share']:.2f} of {a}'s referrals", f"<= {KICKBACK_SHARE}")
               for a in grp.a] + [ev("in_top1_share", f"{r.in_top1_share:.2f} from {r.in_top1}", f"peer median {fx.in_top1_share.median():.2f}")]
        kick(b, list(zip(grp.a, grp.b)), evs, int(ptype[b] in HARM_TYPES))
    for ring in ctx["rings"]:
        ids = ring["providers"]
        rc = c[c.provider_id.isin(ids)]
        shared_m = rc.groupby("member_id").provider_id.nunique()
        rc = rc[rc.member_id.isin(shared_m.index[shared_m >= 2])]
        evs = [ev(col, val, "distinct per provider") for col, val in ring["shared"].items()]
        evs += [ev("referral_cycle", lp, "no referral loops among co-owned providers") for lp in ring["loops"][:5]]
        evs += [ev("reciprocal_referral", rp, "one-way referrals") for rp in ring["reciprocal"][:5]]
        evs += [ev("member_jaccard_mean", ring["member_jaccard"], "< 0.05 typical"), ev("providers", ",".join(ids), "")]
        rows.append({"alert_id": f"GR-{ring['ring_id']}", "lens": "graph", "entity_type": "community",
                     "entity_id": ring["ring_id"], "claim_ids": rc.claim_id.tolist(), "code": "G03",
                     "severity": 4 + int(ring["harm"]), "score": ring["score"],
                     "dollars_at_risk": round(float(rc.paid_amt.sum()), 2), "evidence": evs})
    return pd.DataFrame(rows, columns=S.ALERT_COLUMNS)


def provider_scores(f: pd.DataFrame, alerts: pd.DataFrame) -> pd.Series:
    """Per-provider graph score for ranking: max alert score touching the provider (ring membership counts),
    else a soft signal score capped at 0.5 (concentration, member overlap, propagated risk)."""
    fx = f.set_index("provider_id")
    vol = lambda n: 1 - np.exp(-n / 20)  # noqa: E731
    soft = pd.concat([fx.out_top1_share.fillna(0) * vol(fx.n_out), fx.in_top1_share.fillna(0) * vol(fx.n_in),
                      (3 * fx.member_jaccard_max).clip(upper=1), fx.ppr_pct], axis=1).mean(axis=1) * 0.5
    hit = alerts[alerts.entity_type == "provider"].groupby("entity_id").score.max()
    ring = fx.ring_id.map(alerts[alerts.entity_type == "community"].set_index("entity_id").score)
    return pd.concat([soft, hit.reindex(fx.index), ring], axis=1).max(axis=1).round(3).rename("graph_score")
