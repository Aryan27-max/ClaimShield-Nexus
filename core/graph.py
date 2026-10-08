"""Lens 3: entity graph, referral structure, rings and risk propagation. Run: python -m core.graph"""
import argparse
import hashlib
import time
from itertools import combinations

import networkx as nx
import numpy as np
import pandas as pd
from scipy import sparse

from core import ledger
from core import schema as S
from core import graph_alerts as GA
from core.graph_alerts import HARM_TYPES, RECENT_DAYS, to_alerts

RING_MIN_SIZE, RING_MIN_SCORE = 3, 0.5
LINKS = ["owner_id", "address_id", "bank_id"]
PPR_ALPHA = 0.85


def build_graph(providers: pd.DataFrame, referrals: pd.DataFrame, claims: pd.DataFrame,
                asof: pd.Timestamp = S.END) -> nx.Graph:
    """Provider/member/owner/address/bank graph. Referral edges keep direction in `refs` {from_provider: n};
    treatment edges aggregate claims per (provider, member)."""
    G = nx.Graph()
    p = providers.astype({c: str for c in ["provider_id", "type", "specialty"] + LINKS})
    G.add_nodes_from(((r.provider_id, {"kind": "provider", "type": r.type, "specialty": r.specialty})
                      for r in p.itertuples()))
    for col in LINKS:
        kind = col.removesuffix("_id")
        G.add_nodes_from(p[col].unique(), kind=kind)
        G.add_edges_from(zip(p.provider_id, p[col]), rel=kind, weight=1.0)
    t = claims[claims.service_date <= asof].groupby(["provider_id", "member_id"], observed=True) \
        .agg(n=("claim_id", "size"), paid=("paid_amt", "sum")).reset_index().astype({"provider_id": str, "member_id": str})
    G.add_nodes_from(t.member_id.unique(), kind="member")
    G.add_edges_from(((r.provider_id, r.member_id, {"rel": "treats", "weight": float(r.n), "paid": round(r.paid, 2)})
                      for r in t.itertuples()))
    for (a, b), n in _ref_counts(referrals, asof).items():
        if G.has_edge(a, b):
            G[a][b]["refs"][a] = n
            G[a][b]["weight"] += n
        else:
            G.add_edge(a, b, rel="refers", weight=float(n), refs={a: n})
    return G


def _ref_counts(referrals: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    r = referrals[referrals.date <= asof].astype({"from_provider": str, "to_provider": str})
    return r[r.from_provider != r.to_provider].groupby(["from_provider", "to_provider"]).size()


def _flow_counts(claims: pd.DataFrame, asof: pd.Timestamp, since: pd.Timestamp | None = None) -> pd.Series:
    """Referral volume: referred claims per (referring provider, billing provider)."""
    c = claims[(claims.service_date <= asof) & (claims.service_date > (since or pd.Timestamp.min))]
    c = c.dropna(subset=["referring_provider_id"]).astype({"referring_provider_id": str, "provider_id": str})
    return c[c.referring_provider_id != c.provider_id].groupby(["referring_provider_id", "provider_id"]).size()


def _concentration(counts: pd.Series, level: int, tag: str) -> pd.DataFrame:
    """Top-1 share of a provider's referrals (level 0 = outbound, 1 = inbound)."""
    df = counts.rename("n").reset_index()
    key, other = df.columns[level], df.columns[1 - level]
    tot = df.groupby(key).n.sum()
    top = df.sort_values(["n", other], ascending=[False, True]).drop_duplicates(key).set_index(key)
    return pd.DataFrame({f"n_{tag}": tot, f"{tag}_top1_share": (top.n / tot).round(3), f"{tag}_top1": top[other]})


def _loops(counts: pd.Series) -> tuple[pd.Series, pd.Series, dict]:
    """Reciprocal partners, directed 3-cycles per provider, and the cycle paths."""
    succ: dict[str, set] = {}
    for a, b in counts.index:
        succ.setdefault(a, set()).add(b)
    recip = pd.Series({u: sum(u in succ.get(v, ()) for v in vs) for u, vs in succ.items()}, dtype=float)
    cycles: dict[str, list] = {}
    for u, vs in succ.items():
        for v in vs:
            for w in succ.get(v, ()):
                if w != u and u in succ.get(w, ()):
                    cycles.setdefault(u, []).append(f"{u}->{v}->{w}->{u}")
    return recip, pd.Series({u: len(c) for u, c in cycles.items()}, dtype=float), cycles


def _provider_projection(providers: pd.DataFrame, counts: pd.Series, claims: pd.DataFrame, asof) -> tuple[nx.Graph, dict]:
    """Provider-only graph: shared owner/address/bank, referrals, and co-treated members (Jaccard)."""
    c = claims[claims.service_date <= asof].astype({"provider_id": str, "member_id": str})
    pid = providers.provider_id.astype(str).tolist()
    pi = {p: i for i, p in enumerate(pid)}
    pairs = c.drop_duplicates(["provider_id", "member_id"])
    mcodes, members = pd.factorize(pairs.member_id)
    M = sparse.csr_matrix((np.ones(len(pairs)), (pairs.provider_id.map(pi).values, mcodes)), shape=(len(pid), len(members)))
    size = np.asarray(M.sum(axis=1)).ravel()
    shared = (M @ M.T).tocoo()
    jac = {(pid[i], pid[j]): s / (size[i] + size[j] - s) for i, j, s in zip(shared.row, shared.col, shared.data) if i != j}
    P = nx.Graph()
    P.add_nodes_from(pid)

    def bump(a, b, w):
        P.add_edge(a, b, weight=(P[a][b]["weight"] if P.has_edge(a, b) else 0.0) + w)
    for i, j, s in zip(shared.row, shared.col, shared.data):
        if i < j and s >= 3:
            bump(pid[i], pid[j], 10 * jac[(pid[i], pid[j])])
    for (a, b), n in counts.items():
        bump(a, b, float(np.log1p(n)))
    for a, b in _entity_pairs(providers):
        bump(a, b, 5.0)
    return P, jac


def _entity_pairs(providers: pd.DataFrame) -> list[tuple[str, str]]:
    p = providers.astype({col: str for col in ["provider_id"] + LINKS})
    return [pair for col in LINKS for ids in p.groupby(col).provider_id.apply(list) for pair in combinations(ids, 2)]


def personalized_pagerank(G: nx.Graph, investigations: pd.DataFrame, asof: pd.Timestamp = S.END) -> pd.Series:
    """Risk propagated from past SIU outcomes, as lift over global PageRank (removes the bias toward busy providers).
    Leakage rule: seeds are ONLY investigations with outcome == "confirmed" AND closed < asof (snapshot date);
    open, unfounded, education or later-closed cases never seed, so the score uses only what an SIU knew at asof."""
    seeds = investigations[(investigations.outcome == "confirmed") & (investigations.closed < asof)].provider_id.astype(str)
    seeds = [s for s in seeds if s in G]
    if not seeds:
        return pd.Series(0.0, index=[n for n, k in G.nodes(data="kind") if k == "provider"])
    ppr = nx.pagerank(G, alpha=PPR_ALPHA, personalization={s: 1.0 for s in seeds}, weight="weight")
    base = nx.pagerank(G, alpha=PPR_ALPHA, weight="weight")
    return pd.Series({n: v / base[n] for n, v in ppr.items() if G.nodes[n]["kind"] == "provider"})


def _rings(providers: pd.DataFrame, cycles: dict, recip_pairs: set, jac: dict) -> list[dict]:
    """Candidate rings: providers linked by shared owner/address/bank, scored by link types, loops and member overlap."""
    p = providers.astype({col: str for col in ["provider_id", "type"] + LINKS}).set_index("provider_id")
    E = nx.Graph(_entity_pairs(providers))
    rings = []
    for comp in nx.connected_components(E):
        ids = sorted(comp)
        if len(ids) < RING_MIN_SIZE:
            continue
        sub = p.loc[ids]
        shared = {col: sub[col].value_counts().index[0] for col in LINKS if sub[col].value_counts().iloc[0] > 1}
        loops = sorted({c for u in ids for c in cycles.get(u, []) if set(c.split("->")) <= comp})
        recips = sorted(f"{a}<->{b}" for a, b in recip_pairs if a < b and a in comp and b in comp)
        jm = float(np.mean([jac.get((a, b), 0.0) for k, a in enumerate(ids) for b in ids[k + 1:]]))
        score = 0.4 * len(shared) / 3 + 0.3 * bool(loops or recips) + 0.3 * min(1.0, 3 * jm)
        rings.append({"ring_id": f"RING-{ids[0]}", "providers": ids, "shared": shared, "loops": loops,
                      "reciprocal": recips, "member_jaccard": round(jm, 3), "score": round(score, 3),
                      "harm": bool(set(sub.type) & HARM_TYPES)})
    return rings


def features(providers, referrals, claims, investigations, asof: pd.Timestamp = S.END) -> tuple[pd.DataFrame, dict]:
    """Per-provider graph signals (graph_features.parquet) and context for alerts."""
    G = build_graph(providers, referrals, claims, asof)
    counts = _ref_counts(referrals, asof)
    P, jac = _provider_projection(providers, counts, claims, asof)
    recip, cyc, cycles = _loops(counts)
    pid = providers.provider_id.astype(str)
    f = pd.DataFrame(index=pd.Index(pid, name="provider_id"))
    p = providers.astype({col: str for col in LINKS}).set_index(pid)
    for col in LINKS:
        f[f"shared_{col.removesuffix('_id')}_n"] = p[col].map(p[col].value_counts()) - 1
    flows = _flow_counts(claims, asof)
    f = f.join(_concentration(flows, 0, "out")).join(_concentration(flows, 1, "in")) \
         .join(_concentration(_flow_counts(claims, asof, asof - pd.Timedelta(days=RECENT_DAYS)), 0, "out_recent"))
    f["reciprocal_partners"], f["cycles3"] = recip.reindex(f.index).fillna(0), cyc.reindex(f.index).fillna(0)
    lk = pd.DataFrame([(u, v, jac.get((u, v), 0.0)) for a, b in set(counts.index) | set(_entity_pairs(providers))
                       for u, v in [(a, b), (b, a)]], columns=["u", "v", "j"]).sort_values(["j", "v"], ascending=[False, True])
    lk = lk.drop_duplicates("u").set_index("u")
    f["member_jaccard_max"], f["member_jaccard_with"] = lk.j.round(3).reindex(f.index).fillna(0), lk.v.reindex(f.index)
    comms = nx.community.louvain_communities(P, weight="weight", seed=S.SEED)
    for k, cm in enumerate(sorted(comms, key=lambda c: min(c))):
        idx = list(cm)
        f.loc[idx, "community_id"], f.loc[idx, "community_size"] = f"C{k:03d}", len(cm)
        f.loc[idx, "community_density"] = round(nx.density(P.subgraph(cm)), 4)
    ppr = personalized_pagerank(G, investigations, asof)
    f["ppr_lift"] = ppr.reindex(f.index).fillna(0)
    f["ppr_pct"] = f.ppr_lift.rank(pct=True).round(4)
    rings = [r for r in _rings(providers, cycles, {(a, b) for a, b in counts.index if (b, a) in counts.index}, jac)
             if r["score"] >= RING_MIN_SCORE and (r["loops"] or r["reciprocal"])]
    f["ring_id"] = pd.Series({p: r["ring_id"] for r in rings for p in r["providers"]}).reindex(f.index)
    for c in ["n_out", "n_in", "n_out_recent"]:
        f[c] = f[c].fillna(0).astype(int)
    return f.reset_index(), {"G": G, "rings": rings}


def run_graph(t: dict, asof: pd.Timestamp = S.END) -> tuple[pd.DataFrame, pd.DataFrame, nx.Graph]:
    """Returns (alerts, graph_features, graph)."""
    f, ctx = features(t["providers"], t["referrals"], t["claims"], t["investigations"], asof)
    alerts = to_alerts(f, ctx, t["claims"], t["providers"], asof)
    return alerts, f.assign(graph_score=GA.provider_scores(f, alerts).values), ctx["G"]


def ego_graph(entity_id: str, max_nodes: int = 150, G: nx.Graph | None = None,
              graph_features: pd.DataFrame | None = None) -> nx.Graph:
    """Small subgraph around a provider/member/... or a ring id; non-member nodes first, then members by weight."""
    if G is None:
        G = build_graph(*(S.load(n) for n in ["providers", "referrals", "claims"]))
    if entity_id in G:
        centers = [entity_id]
    else:
        gf = graph_features if graph_features is not None else S.load("graph_features")
        centers = gf.provider_id[gf.ring_id == entity_id].tolist()
    keep = list(dict.fromkeys(centers))[:max_nodes]
    for hop in range(2):
        frontier = []
        for u in keep:
            for v, d in G[u].items():
                if v not in keep:
                    frontier.append((G.nodes[v]["kind"] == "member", -d.get("weight", 1.0), v))
        for _, _, v in sorted(set(frontier)):
            if len(keep) >= max_nodes:
                break
            if v not in keep:
                keep.append(v)
    return G.subgraph(keep).copy()


def log_run(alerts: pd.DataFrame, f: pd.DataFrame, runtime_s: float, db=None) -> None:
    ids = ",".join(sorted(alerts.alert_id))
    ledger.append("system:graph", "lens_run", {
        "lens": "graph", "n_providers": len(f), "n_alerts": len(alerts), "by_code": alerts.code.value_counts().to_dict(),
        "n_rings": int((alerts.entity_type == "community").sum()), "n_communities": int(f.community_id.nunique()),
        "params": {"kickback_share": GA.KICKBACK_SHARE, "recent_days": RECENT_DAYS, "seed": S.SEED, "ppr_alpha": PPR_ALPHA},
        "dollars_at_risk": round(float(alerts.dollars_at_risk.sum()), 2),
        "alerts_sha": hashlib.sha256(ids.encode()).hexdigest(), "runtime_s": round(runtime_s, 2),
    }, db)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-ledger", action="store_true", help="dev: start a fresh ledger before logging")
    if ap.parse_args().reset_ledger:
        ledger.reset()
    t0 = time.time()
    t = {n: S.load(n) for n in ["providers", "referrals", "claims", "investigations"]}
    alerts, f, _ = run_graph(t)
    runtime = time.time() - t0
    alerts.to_parquet(S.OUT / "alerts_graph.parquet", index=False)
    f.to_parquet(S.OUT / "graph_features.parquet", index=False)
    log_run(alerts, f, runtime)
    print(alerts[["alert_id", "code", "severity", "score", "dollars_at_risk"]].to_string(index=False))
    print(f"{len(alerts)} alerts in {runtime:.1f}s; ledger verify = {ledger.verify()}")


if __name__ == "__main__":
    main()
