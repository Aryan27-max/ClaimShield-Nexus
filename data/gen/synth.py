"""Synthetic Medicaid claims generator with planted FWA schemes. Run: python -m data.gen.synth"""
import hashlib
import time

import numpy as np
import pandas as pd

from core import schema as S
from data.gen import legit, schemes

def _mix(em_share: float, extra: dict) -> dict:
    return {**{k: v * em_share for k, v in zip(S.EM_LEVELS, S.EM_BASE_MIX)}, **extra}


# specialty -> (type, count, median claims over 18 months, code mix)
SPECIALTIES = {
    "family_medicine": ("prof", 230, 60, _mix(.88, {"93000": .04, "81001": .04, "20610": .04})),
    "internal_medicine": ("prof", 130, 60, _mix(.88, {"93000": .06, "81001": .06})),
    "pediatrics": ("prof", 90, 60, _mix(.95, {"81001": .05})),
    "emergency_medicine": ("prof", 50, 70, {"99283": .3, "99284": .4, "99285": .25, "93010": .05}),
    "orthopedics": ("prof", 50, 50, _mix(.65, {"20610": .35})),
    "oncology": ("prof", 25, 60, _mix(.3, {"96413": .3, "96360": .1, "J9271": .3})),
    "cardiology": ("prof", 45, 60, _mix(.5, {"93000": .3, "93010": .2})),
    "physical_therapy": ("prof", 70, 70, {"97110": .45, "97140": .3, "97530": .25}),
    "radiology": ("prof", 70, 60, {"71046": .5, "70450": .35, "70470": .15}),
    "behavioral_health": ("bh", 90, 80, {"90791": .1, "90834": .5, "90837": .4}),
    "hospital": ("facility", 60, 170, {"99283": .2, "99284": .2, "99285": .1, "71046": .15,
                                       "70450": .1, "80053": .1, "85025": .15}),
    "clinical_lab": ("lab", 60, 130, {"80053": .25, "80048": .15, "85025": .25, "85027": .1,
                                      "36415": .15, "81001": .1}),
    "dme_supplier": ("dme", 60, 60, {"E0601": .15, "K0001": .1, "E0260": .05, "L1832": .2, "A4253": .5}),
    "home_health": ("home_health", 60, 70, {"G0299": .5, "G0156": .5}),
    "ambulance": ("ambulance", 40, 60, {"A0427": .5, "A0425": .5}),
    "pharmacy": ("pharmacy", 70, 100, {"RX100": .8, "RX200": .2}),
}
REFERRER_SPECS = ["family_medicine", "internal_medicine", "pediatrics", "cardiology", "orthopedics", "oncology"]
NEEDS_REF = ["lab", "dme", "home_health", "pharmacy"]
POS = {"prof": "11", "facility": "22", "pharmacy": "01", "lab": "81", "ambulance": "41",
       "bh": "11", "home_health": "12", "dme": "12"}
CLAIM_TYPE = {"facility": "institutional", "pharmacy": "pharmacy", "dme": "dme"}
DX = {"em": ["I10", "E11.9", "J06.9", "M54.5", "Z00.00"], "er": ["R07.9", "S06.0X0A", "J18.9", "R10.9"],
      "bh": ["F32.9", "F41.1", "F43.10"], "pt": ["M54.5", "M25.561", "S83.511A"],
      "lab": ["E11.9", "E78.5", "Z00.00"], "rad": ["R07.9", "S06.0X0A"], "card": ["I10", "I48.91"],
      "proc": ["M17.11"], "onc": ["C34.90", "C50.919"], "dme": ["G47.33", "E11.9", "M17.11"],
      "hh": ["I50.9", "E11.9"], "amb": ["R07.9", "S06.0X0A"], "rx": ["I10", "E11.9", "F32.9"]}
SKEL = ["provider_id", "member_id", "cpt", "units", "service_date", "submit_date", "referring_provider_id",
        "facility_id", "modifier", "claim_type", "pos", "dx", "_bf", "_pf"]
NDAYS = (S.END - S.START).days + 1


def _jitter(rng, cl, sd):
    lat = np.array([c[1] for c in S.CLUSTERS])[cl] + rng.normal(0, sd, len(cl))
    lon = np.array([c[2] for c in S.CLUSTERS])[cl] + rng.normal(0, sd, len(cl))
    return lat.round(4), lon.round(4)


def make_members(rng) -> pd.DataFrame:
    n = S.N_MEMBERS
    share = np.array([c[3] for c in S.CLUSTERS])
    cl = rng.choice(len(S.CLUSTERS), n, p=share / share.sum())
    lat, lon = _jitter(rng, cl, 0.15)
    dob = S.END - pd.to_timedelta(rng.integers(0, 90 * 365, n), unit="D")
    dies = rng.random(n) < 0.02
    dod = pd.Series(S.START + pd.to_timedelta(rng.integers(30, NDAYS - 30, n), unit="D")).where(dies)
    return pd.DataFrame({
        "member_id": [f"M{i:05d}" for i in range(n)], "dob": dob, "dod": dod,
        "gender": rng.choice(["F", "M"], n), "zip": [f"7{c}{z:03d}" for c, z in zip(cl, rng.integers(0, 1000, n))],
        "lat": lat, "lon": lon, "plan": rng.choice(["MCO_A", "MCO_B", "FFS"], n, p=[.45, .4, .15]),
        "cluster": cl,
    })


def make_providers(rng):
    spec = np.concatenate([[s] * v[1] for s, v in SPECIALTIES.items()])
    n = len(spec)
    share = np.array([c[3] for c in S.CLUSTERS])
    cl = rng.choice(len(S.CLUSTERS), n, p=share / share.sum())
    lat, lon = _jitter(rng, cl, 0.12)
    pid = np.array([f"P{i:04d}" for i in range(n)])
    owner = np.array([f"O{i:04d}" for i in range(n)], dtype=object)
    hosp = np.flatnonzero(spec == "hospital")
    for g in range(3):  # legit hospital systems: shared owner + bank, distinct addresses
        same = hosp[cl[hosp] == cl[hosp[g * 7]]][:5]
        owner[same] = owner[same[0]]
    late = rng.random(n) < 0.08
    enroll = np.where(late, S.START + pd.to_timedelta(rng.integers(0, 360, n), unit="D"),
                      S.START - pd.to_timedelta(rng.integers(200, 3000, n), unit="D"))
    providers = pd.DataFrame({
        "provider_id": pid, "npi": (rng.choice(900_000_000, n, replace=False) + 1_000_000_000).astype(str),
        "name": [f"{s.replace('_', ' ').title()} Provider {i}" for i, s in enumerate(spec)],
        "specialty": spec, "type": [SPECIALTIES[s][0] for s in spec], "enroll_date": pd.to_datetime(enroll),
        "address_id": [f"A{i:05d}" for i in range(n)], "owner_id": owner, "bank_id": ["B" + o[1:] for o in owner],
        "excluded_flag": False, "lat": lat, "lon": lon, "cluster": cl,
    })
    n_cl = 30
    ccl = rng.choice(len(S.CLUSTERS), n_cl, p=share / share.sum())
    clat, clon = _jitter(rng, ccl, 0.12)
    addresses = pd.concat([
        pd.DataFrame({"address_id": providers.address_id, "lat": lat, "lon": lon, "cluster": cl}),
        pd.DataFrame({"address_id": [f"A{n + i:05d}" for i in range(n_cl)], "lat": clat, "lon": clon, "cluster": ccl}),
    ], ignore_index=True)
    addresses["line"] = [f"{100 + i} Synthetic St" for i in range(len(addresses))]
    addresses["zip"] = [f"7{c}{i % 1000:03d}" for i, c in enumerate(addresses.cluster)]
    fac_addr = pd.concat([providers.loc[hosp, "address_id"], addresses.address_id.iloc[n:]])
    facilities = addresses.set_index("address_id").loc[fac_addr].reset_index()
    facilities.insert(0, "facility_id", [f"F{i:03d}" for i in range(len(facilities))])
    facilities["type"] = ["hospital"] * len(hosp) + ["clinic"] * n_cl
    owners = pd.DataFrame({"owner_id": pd.unique(owner)})
    owners["name_hash"] = [hashlib.sha256(o.encode()).hexdigest()[:16] for o in owners.owner_id]
    return providers, owners, addresses, facilities


def fill(skel: pd.DataFrame, ctx: dict, rng) -> pd.DataFrame:
    """Complete a claim skeleton (provider, member, cpt, service_date at minimum) with derived fields."""
    df = skel.reset_index(drop=True).copy()
    for c in SKEL:
        if c not in df:
            df[c] = pd.NA
    df = df.astype({"referring_provider_id": object, "facility_id": object, "modifier": object})
    pinfo, tbl = ctx["pinfo"], ctx["cpt"]
    typ, spec, cl = (df.provider_id.map(pinfo[c]) for c in ["type", "specialty", "cluster"])
    lo, hi = df.cpt.map(tbl.units_lo), df.cpt.map(tbl.units_hi)
    df["units"] = df.units.fillna(lo + np.floor(rng.random(len(df)) * (hi - lo + 1))).astype(int)
    need = df.referring_provider_id.isna() & (typ.isin(NEEDS_REF) | (spec == "radiology"))
    for c, idx in df.index[need].groupby(cl[need]).items():
        df.loc[idx, "referring_provider_id"] = rng.choice(ctx["ref_by_cl"][c], len(idx))
    isfac = typ == "facility"
    df.loc[isfac, "facility_id"] = df.provider_id[isfac].map(ctx["fac_of"])
    er = (spec == "emergency_medicine") & df.facility_id.isna()
    for c, idx in df.index[er].groupby(cl[er]).items():
        df.loc[idx, "facility_id"] = rng.choice(ctx["hosp_by_cl"][c], len(idx))
    df["pos"] = np.where(spec == "emergency_medicine", "23", np.where(spec == "radiology", "22", typ.map(POS)))
    df["claim_type"] = typ.map(CLAIM_TYPE).fillna("professional")
    cat = df.cpt.map(tbl.category)
    for k, idx in df.index.groupby(cat).items():
        df.loc[idx, "dx"] = rng.choice(DX[k], len(idx))
    df["submit_date"] = pd.to_datetime(df.submit_date).fillna(df.service_date + pd.to_timedelta(rng.integers(1, 31, len(df)), unit="D"))
    em25 = (cat == "em") & (rng.random(len(df)) < 0.06)
    df["modifier"] = df.modifier.fillna(pd.Series(np.where(em25, "25", ""), index=df.index))
    df["_bf"] = df._bf.fillna(pd.Series(rng.uniform(1.1, 1.6, len(df)))).astype(float)
    df["_pf"] = df._pf.fillna(pd.Series(rng.uniform(0.85, 1.0, len(df)))).astype(float)
    return df[SKEL]


def base_claims(rng, members, providers, ctx) -> pd.DataFrame:
    mem_by_cl = ctx["mem_by_cl"]
    parts = []
    for p in providers.itertuples():
        _, _, median, mix = SPECIALTIES[p.specialty]
        n = max(5, int(rng.lognormal(np.log(median), 0.5)))
        panel = rng.choice(mem_by_cl[p.cluster], size=max(5, n // 3), replace=False)
        w = np.array(list(mix.values()))
        parts.append(pd.DataFrame({
            "provider_id": p.provider_id, "member_id": rng.choice(panel, n),
            "cpt": rng.choice(list(mix), n, p=w / w.sum()),
            "service_date": S.START + pd.to_timedelta(rng.integers(0, NDAYS, n), unit="D"),
        }))
    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates(["member_id", "provider_id", "cpt", "service_date"])
    key = df.member_id + "|" + df.provider_id + "|" + df.service_date.astype(str)
    for c1, c2 in S.NCCI_PAIRS:
        df = df[~((df.cpt == c2) & key.isin(set(key[df.cpt == c1])))]
        key = key.loc[df.index]
    dod = df.member_id.map(members.set_index("member_id").dod)
    df = df[~(df.service_date > dod)]
    return fill(df, ctx, rng)


def finalize(claims: pd.DataFrame, providers: pd.DataFrame, ctx: dict) -> pd.DataFrame:
    enroll = claims.provider_id.map(providers.set_index("provider_id").enroll_date)
    df = claims[claims.service_date >= enroll].copy()
    tbl = ctx["cpt"]
    fee = df.cpt.map(tbl.fee)
    df["minutes"] = (df.units * df.cpt.map(tbl.minutes_per_unit)).astype(int)
    df["billed_amt"] = (fee * df.units * df._bf).round(2)
    df["paid_amt"] = (fee * df.units * df._pf).round(2)
    df = df.sort_values(["service_date", "provider_id", "member_id"], kind="stable").reset_index(drop=True)
    df.insert(0, "claim_id", [f"C{i:07d}" for i in range(len(df))])
    df = df.drop(columns=["_bf", "_pf"])
    for c in ["member_id", "provider_id", "facility_id", "referring_provider_id", "claim_type", "cpt", "modifier", "dx", "pos"]:
        df[c] = df[c].astype("category")
    return df[["claim_id", "member_id", "provider_id", "facility_id", "referring_provider_id", "claim_type",
               "service_date", "submit_date", "cpt", "modifier", "units", "minutes", "dx", "pos",
               "billed_amt", "paid_amt"]]


def make_referrals(claims, ctx, rng) -> pd.DataFrame:
    r = (claims.dropna(subset=["referring_provider_id"])
         .groupby(["referring_provider_id", "provider_id", "member_id"], observed=True).service_date.min().reset_index())
    r.columns = ["from_provider", "to_provider", "member_id", "date"]
    r["date"] = r.date - pd.to_timedelta(rng.integers(1, 15, len(r)), unit="D")
    df = pd.concat([r.astype({c: object for c in r.columns[:3]}), pd.DataFrame(ctx["extra_referrals"], columns=r.columns)],
                   ignore_index=True)
    df.insert(0, "ref_id", [f"R{i:06d}" for i in range(len(df))])
    return df


def generate(seed: int = S.SEED) -> dict:
    rng = np.random.default_rng(seed)
    members = make_members(rng)
    providers, owners, addresses, facilities = make_providers(rng)
    hosp = facilities[facilities.type == "hospital"]
    refs = providers[providers.specialty.isin(REFERRER_SPECS)]
    ctx = {
        "cpt": S.cpt_table(), "pinfo": providers.set_index("provider_id")[["type", "specialty", "cluster"]],
        "ref_by_cl": refs.groupby("cluster").provider_id.apply(np.array).to_dict(),
        "hosp_by_cl": hosp.groupby("cluster").facility_id.apply(np.array).to_dict(),
        "fac_of": dict(zip(providers.loc[providers.type == "facility", "provider_id"], hosp.facility_id)),
        "mem_by_cl": members.groupby("cluster").member_id.apply(np.array).to_dict(), "extra_referrals": [], "fill": lambda sk: fill(sk, ctx, rng),
    }
    claims = base_claims(rng, members, providers, ctx)
    ctx["free"] = set(providers.provider_id)
    ctx["vol"] = claims.provider_id.value_counts()
    outliers = legit.outliers(claims, providers, rng, ctx)
    claims = pd.concat([claims, outliers.pop("claims")], ignore_index=True)
    gt = []
    for inject in schemes.INJECTORS:
        claims = inject(claims, providers, members, gt, rng, ctx)
    honest = legit.honest_error(claims, providers, rng, ctx)
    claims = honest["claims"]
    claims = finalize(schemes.drop_post_death(claims, members, gt), providers, ctx)
    assert len(claims) <= S.MAX_CLAIMS, len(claims)
    ground_truth = pd.DataFrame(gt, columns=["entity_id", "scheme", "start_date"])
    return {
        "members": members.drop(columns="cluster"), "providers": providers.drop(columns=["lat", "lon", "cluster"]),
        "facilities": facilities[["facility_id", "address_id", "lat", "lon", "type"]],
        "addresses": addresses[["address_id", "line", "zip", "lat", "lon"]], "owners": owners,
        "referrals": make_referrals(claims, ctx, rng), "claims": claims,
        "investigations": schemes.investigations(ground_truth, providers, outliers["ids"], rng),
        "ground_truth": ground_truth, "legit_outliers": pd.concat([outliers["table"], honest["table"]], ignore_index=True),
    }


def main() -> None:
    t0 = time.time()
    tables = generate()
    S.OUT.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(S.OUT / f"{name}.parquet", index=False)
    for name in ["ground_truth", "legit_outliers"]:
        tables[name].to_csv(S.OUT / f"{name}.csv", index=False)
    for name, df in tables.items():
        print(f"{name:15s} {len(df):>8,d} rows")
    print(tables["ground_truth"].scheme.value_counts().to_string())
    print(f"generated in {time.time() - t0:.1f}s -> {S.OUT}")


if __name__ == "__main__":
    main()
