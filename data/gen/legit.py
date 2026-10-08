"""Legitimate outliers and honest billing errors: realistic noise the lenses must NOT escalate."""
import pandas as pd

from core import schema as S
from data.gen.schemes import _days, _pick


def outliers(claims, providers, rng, ctx) -> dict:
    """4 high-cost oncology + 3 busy ER providers: extreme but legitimate volume (not FWA, not in ground_truth)."""
    onc = _pick(providers, ctx, rng, 4, providers.specialty == "oncology")
    er = _pick(providers, ctx, rng, 3, providers.specialty == "emergency_medicine")
    parts = []
    for pid, n, codes, w in [(p, 250, ["96413", "J9271"], [.4, .6]) for p in onc] + \
                            [(p, 2500, ["99285", "99284", "99283"], [.5, .35, .15]) for p in er]:
        own = claims[claims.provider_id == pid]
        mem = own.member_id.unique() if pid in onc else ctx["mem_by_cl"][ctx["pinfo"].cluster[pid]]
        sk = pd.DataFrame({"provider_id": pid, "member_id": rng.choice(mem, n), "cpt": rng.choice(codes, n, p=w),
                           "service_date": S.START + _days(rng, n)})
        key = ["member_id", "cpt", "service_date"]
        both = pd.concat([own[key], sk[key]], ignore_index=True)
        parts.append(sk[~both.duplicated(key).values[len(own):]])
    table = pd.DataFrame({"entity_id": onc + er, "kind": ["high_cost_oncology"] * 4 + ["busy_er"] * 3})
    return {"claims": ctx["fill"](pd.concat(parts)), "ids": onc + er, "table": table}


def honest_error(claims, providers, rng, ctx) -> dict:
    """~15 clean providers with 1-3 one-off billing slips that trip a single rule (not FWA, not in ground_truth)."""
    vol, mue = ctx["vol"], claims.cpt.map(ctx["cpt"].mue)
    mue = mue.where(mue <= 8, 0)  # only small-MUE codes, so "+1 unit" stays a slip
    enroll = claims.provider_id.map(providers.set_index("provider_id").enroll_date)
    ok = claims.provider_id.isin(ctx["free"]) & (claims.service_date >= enroll + pd.Timedelta(days=1))
    c1 = claims.cpt.isin([a for a, _ in S.NCCI_PAIRS]) & ok
    pools = {
        "dup": claims.provider_id[ok & claims.provider_id.map(ctx["pinfo"].type).isin(["prof", "lab"])],
        "ncci": claims.provider_id[c1], "mue": claims.provider_id[ok & (mue > 1)],
    }
    add, ids, kinds = [], [], []
    for kind, n_min, n_max in [("dup", 1, 3), ("ncci", 1, 2), ("mue", 1, 1)]:
        cand = sorted(set(pools[kind]) & ctx["free"] & set(vol.index[vol >= 20]))
        for pid in rng.choice(cand, 5, replace=False):
            ctx["free"].discard(pid)
            k = int(rng.integers(n_min, n_max + 1))
            if kind == "dup":  # corrected resubmission: same line re-sent weeks later
                d = claims[ok & (claims.provider_id == pid)].sample(k, random_state=int(rng.integers(1e9))).copy()
                d["submit_date"] = d.submit_date + _days(rng, k, 20, 60)
                add.append(d)
            elif kind == "ncci":  # bundled code billed once without modifier
                d = claims[c1 & (claims.provider_id == pid)].sample(k, random_state=int(rng.integers(1e9))).copy()
                d["cpt"], d["units"], d["modifier"] = d.cpt.map(dict(S.NCCI_PAIRS)), 1, ""
                add.append(d)
            else:  # MUE breached by one unit, once
                i = claims.index[ok & (claims.provider_id == pid) & (mue > 1)]
                i = rng.choice(i, 1)
                claims.loc[i, "units"] = mue[i].astype(int) + 1
            ids.append(pid)
            kinds.append(kind)
    table = pd.DataFrame({"entity_id": ids, "kind": "honest_error", "detail": kinds})
    return {"claims": pd.concat([claims, *add], ignore_index=True), "table": table}
