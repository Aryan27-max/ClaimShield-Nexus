"""Planted FWA scheme injectors, legit outliers and investigation history."""
import numpy as np
import pandas as pd

from core import schema as S

UPCODE_MIX = [0.0, 0.03, 0.12, 0.35, 0.50]


def _days(rng, n, lo=0, hi=None):
    hi = (S.END - S.START).days + 1 if hi is None else hi
    return pd.to_timedelta(rng.integers(lo, hi, n), unit="D")


def _start(rng) -> pd.Timestamp:
    return S.START + pd.Timedelta(days=int(rng.integers(90, 456)))


def _dates_after(rng, start, n):
    return start + _days(rng, n, 0, (S.END - start).days + 1)


def _pick(providers, ctx, rng, n, mask, min_vol=0) -> list:
    vol = providers.provider_id.map(ctx["vol"]).fillna(0)
    cand = providers.provider_id[mask & providers.provider_id.isin(ctx["free"]) & (vol >= min_vol)]
    ids = list(rng.choice(cand.values, n, replace=False))
    ctx["free"] -= set(ids)
    return ids


def _post(claims, pid, start):
    return (claims.provider_id == pid) & (claims.service_date >= start)


def legit_outliers(claims, providers, rng, ctx) -> dict:
    onc = _pick(providers, ctx, rng, 4, providers.specialty == "oncology")
    er = _pick(providers, ctx, rng, 3, providers.specialty == "emergency_medicine")
    parts = []
    for pid, n, codes, w in [(p, 250, ["96413", "J9271"], [.4, .6]) for p in onc] + \
                            [(p, 2500, ["99285", "99284", "99283"], [.5, .35, .15]) for p in er]:
        mem = claims.member_id[claims.provider_id == pid].unique()
        sk = pd.DataFrame({"provider_id": pid, "member_id": rng.choice(mem, n), "cpt": rng.choice(codes, n, p=w),
                           "service_date": S.START + _days(rng, n)})
        parts.append(sk.drop_duplicates(["member_id", "cpt", "service_date"]))
    table = pd.DataFrame({"entity_id": onc + er, "kind": ["high_cost_oncology"] * 4 + ["busy_er"] * 3})
    return {"claims": ctx["fill"](pd.concat(parts)), "ids": onc + er, "table": table}


def duplicate_billing(claims, providers, members, gt, rng, ctx):
    ids = _pick(providers, ctx, rng, 8, providers.type.isin(["prof", "lab", "facility"]), min_vol=120)
    dups = []
    for pid in ids:
        start = _start(rng)
        rows = claims[_post(claims, pid, start)]
        d = rows.sample(frac=0.2, random_state=int(rng.integers(1e9))).copy()
        d["submit_date"] = d.submit_date + _days(rng, len(d), 7, 46)
        dups.append(d)
        gt.append((pid, "duplicate_billing", start))
    return pd.concat([claims, *dups], ignore_index=True)


def upcoding(claims, providers, members, gt, rng, ctx):
    ids = _pick(providers, ctx, rng, 10, providers.specialty.isin(["family_medicine", "internal_medicine"]), 60)
    for pid in ids:
        start = _start(rng)
        m = _post(claims, pid, start) & claims.cpt.isin(S.EM_LEVELS)
        claims.loc[m, "cpt"] = rng.choice(S.EM_LEVELS, m.sum(), p=UPCODE_MIX)
        gt.append((pid, "upcoding", start))
    return claims


def unbundling(claims, providers, members, gt, rng, ctx):
    ids = _pick(providers, ctx, rng, 5, providers.type == "lab", 80) + \
          _pick(providers, ctx, rng, 3, providers.specialty == "cardiology", 40)
    add = []
    for pid in ids:
        start = _start(rng)
        for c1, c2 in S.NCCI_PAIRS:
            rows = claims[_post(claims, pid, start) & (claims.cpt == c1)]
            d = rows[rng.random(len(rows)) < 0.5].copy()
            d["cpt"], d["units"] = c2, 1
            d["_bf"], d["_pf"] = rng.uniform(1.1, 1.6, len(d)), rng.uniform(0.85, 1.0, len(d))
            add.append(d)
        gt.append((pid, "unbundling", start))
    return pd.concat([claims, *add], ignore_index=True)


def _far_clusters() -> dict:
    lat = np.radians([c[1] for c in S.CLUSTERS])
    lon = np.radians([c[2] for c in S.CLUSTERS])
    dl, dn = lat[:, None] - lat[None, :], lon[:, None] - lon[None, :]
    km = 2 * 6371 * np.arcsin(np.sqrt(np.sin(dl / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dn / 2) ** 2))
    return {i: list(np.flatnonzero(km[i] > S.GEO_IMPOSSIBLE_KM + 100)) for i in range(len(S.CLUSTERS))}


def phantom_services(claims, providers, members, gt, rng, ctx):
    ids = _pick(providers, ctx, rng, 6, providers.specialty.isin(["family_medicine", "internal_medicine"]), 30)
    far = _far_clusters()
    mcl = claims.member_id.map(members.set_index("member_id").cluster)
    parts = []
    for i, pid in enumerate(ids):
        start, cl = _start(rng), ctx["pinfo"].cluster[pid]
        dead = members[(members.cluster == cl) & (members.dod < S.END - pd.Timedelta(days=20))]
        dead = dead.sample(min(12, len(dead)), random_state=int(rng.integers(1e9)))
        dates = dead.dod.clip(lower=start) + _days(rng, len(dead), 3, 90)
        parts.append(pd.DataFrame({"provider_id": pid, "member_id": dead.member_id.values,
                                   "service_date": dates.clip(upper=S.END).values}))
        away = claims[mcl.isin(far[cl]) & (claims.service_date >= start)].drop_duplicates(["member_id", "service_date"])
        away = away.sample(min(15, len(away)), random_state=int(rng.integers(1e9)))
        parts.append(pd.DataFrame({"provider_id": pid, "member_id": away.member_id.values,
                                   "service_date": away.service_date.values}))
        if i < 2:
            providers.loc[providers.provider_id == pid, "excluded_flag"] = True
        gt.append((pid, "phantom_services", start))
    sk = pd.concat(parts, ignore_index=True)
    sk["cpt"] = rng.choice(["99214", "99215"], len(sk))
    return pd.concat([claims, ctx["fill"](sk)], ignore_index=True)


def excessive_units(claims, providers, members, gt, rng, ctx):
    spec = ["physical_therapy", "ambulance", "dme_supplier", "home_health"]
    ids = _pick(providers, ctx, rng, 8, providers.specialty.isin(spec), 40)
    mue = claims.cpt.map(ctx["cpt"].mue)
    for pid in ids:
        start = _start(rng)
        m = _post(claims, pid, start) & (mue > 1) & (rng.random(len(claims)) < 0.35)
        claims.loc[m, "units"] = (mue[m] + np.ceil(rng.uniform(0.25, 1.0, m.sum()) * mue[m])).astype(int)
        gt.append((pid, "excessive_units", start))
    return claims


def impossible_timing(claims, providers, members, gt, rng, ctx):
    ids = _pick(providers, ctx, rng, 6, providers.type == "bh", 40)
    parts = []
    for pid in ids:
        start, cl = _start(rng), ctx["pinfo"].cluster[pid]
        pool = members.member_id[(members.cluster == cl) & members.dod.isna()].values
        for day in pd.unique(_dates_after(rng, start, 25)):
            k = int(rng.integers(26, 33))
            parts.append(pd.DataFrame({"provider_id": pid, "member_id": rng.choice(pool, k, replace=False),
                                       "service_date": day, "cpt": "90837"}))
        gt.append((pid, "impossible_timing", start))
    return pd.concat([claims, ctx["fill"](pd.concat(parts, ignore_index=True))], ignore_index=True)


def dme_ring(claims, providers, members, gt, rng, ctx):
    parts = []
    for ring in range(2):
        start, cl = _start(rng), ring  # rings live in the two largest regions
        inc = providers.cluster == cl
        profs = _pick(providers, ctx, rng, 2, inc & providers.specialty.isin(["family_medicine", "internal_medicine"]))
        dme, lab, hh = (_pick(providers, ctx, rng, 1, inc & (providers.type == t))[0] for t in ["dme", "lab", "home_health"])
        ids = profs + [dme, lab, hh]
        hub = providers.provider_id == dme
        for col in ["owner_id", "address_id", "bank_id", "lat", "lon"]:
            providers.loc[providers.provider_id.isin(ids), col] = providers.loc[hub, col].iloc[0]
        providers.loc[hub, "enroll_date"] = start - pd.Timedelta(days=45)
        pool = members.member_id[(members.cluster == cl) & members.dod.isna()].sample(
            100, random_state=int(rng.integers(1e9))).values
        for pid, n, codes in [(profs[0], 60, ["99214", "99215"]), (profs[1], 60, ["99214", "99215"]),
                              (dme, 150, ["E0601", "K0001", "E0260", "L1832"]), (lab, 120, ["80053", "85025"]),
                              (hh, 100, ["G0299"])]:
            sk = pd.DataFrame({"provider_id": pid, "member_id": rng.choice(pool, n), "cpt": rng.choice(codes, n),
                               "service_date": _dates_after(rng, start, n)})
            if pid not in profs:
                sk["referring_provider_id"] = rng.choice(profs, n)
            parts.append(sk.drop_duplicates(["member_id", "cpt", "service_date"]))
        for a, b in [(profs[0], profs[1]), (profs[1], profs[0]), (dme, lab), (lab, profs[0]), (hh, dme)]:
            for m in rng.choice(pool, 30, replace=False):
                ctx["extra_referrals"].append((a, b, m, _dates_after(rng, start, 1)[0]))
        gt.extend((pid, "dme_ring", start) for pid in ids)
    return pd.concat([claims, ctx["fill"](pd.concat(parts, ignore_index=True))], ignore_index=True)


def kickback_referral(claims, providers, members, gt, rng, ctx):
    parts = []
    for t in ["lab", "dme", "home_health"]:
        start = _start(rng)
        recv = _pick(providers, ctx, rng, 1, (providers.type == t) & providers.cluster.isin([0, 1, 2, 3]))[0]
        cl = ctx["pinfo"].cluster[recv]
        refs = _pick(providers, ctx, rng, 2, (providers.cluster == cl) &
                     providers.specialty.isin(["family_medicine", "internal_medicine"]), 30)
        others = [p for p in ctx["ref_by_cl"][cl] if p not in refs]
        for r in refs:
            m = (claims.referring_provider_id == r) & (claims.service_date >= start)
            claims.loc[m, "referring_provider_id"] = rng.choice(others, m.sum())
            pats = claims.member_id[claims.provider_id == r].unique()
            n = int(rng.integers(70, 111))
            sk = pd.DataFrame({"provider_id": recv, "member_id": rng.choice(pats, n), "referring_provider_id": r,
                               "service_date": _dates_after(rng, start, n)})
            sk["cpt"] = rng.choice(list(ctx["cpt"].index[ctx["cpt"].category == {"lab": "lab", "dme": "dme",
                                                                                 "home_health": "hh"}[t]]), n)
            parts.append(sk.drop_duplicates(["member_id", "cpt", "service_date"]))
            gt.append((r, "kickback_referral", start))
        gt.append((recv, "kickback_referral", start))
    return pd.concat([claims, ctx["fill"](pd.concat(parts, ignore_index=True))], ignore_index=True)


INJECTORS = [duplicate_billing, upcoding, unbundling, phantom_services, excessive_units,
             impossible_timing, dme_ring, kickback_referral]


def investigations(gt: pd.DataFrame, providers: pd.DataFrame, outlier_ids: list, rng) -> pd.DataFrame:
    """~60 historical SIU cases with mixed outcomes."""
    ent = gt.drop_duplicates("entity_id").reset_index(drop=True)
    conf = ent.iloc[rng.choice(len(ent), 22, replace=False)]
    clean = providers.provider_id[~providers.provider_id.isin(set(ent.entity_id) | set(outlier_ids))].values
    rest = rng.choice(clean, 28, replace=False)
    up = ent[(ent.scheme == "upcoding") & ~ent.entity_id.isin(conf.entity_id)].entity_id.values[:3]
    last_open = S.END - pd.Timedelta(days=30)
    opened = (conf.start_date + _days(rng, len(conf), 60, 200)).clip(upper=last_open)
    rows = [(p, o, "confirmed") for p, o in zip(conf.entity_id, opened)]
    unf = list(outlier_ids) + list(rest[:16])
    edu = list(up) + list(rest[16:])
    rows += [(p, S.START + _days(rng, 1, 0, 480)[0], "unfounded") for p in unf]
    rows += [(p, S.START + _days(rng, 1, 0, 480)[0], "education") for p in edu]
    df = pd.DataFrame(rows, columns=["provider_id", "opened", "outcome"])
    df["closed"] = (df.opened + _days(rng, len(df), 30, 150)).clip(upper=S.END)
    df["recovered_amt"] = np.where(df.outcome == "confirmed", rng.uniform(5e3, 1.5e5, len(df)).round(-2),
                                   np.where(df.outcome == "education", rng.uniform(0, 3e3, len(df)).round(-2), 0.0))
    df = df.sort_values("opened").reset_index(drop=True)
    df.insert(0, "case_id", [f"INV{i:03d}" for i in range(len(df))])
    return df[["case_id", "provider_id", "opened", "closed", "outcome", "recovered_amt"]]
