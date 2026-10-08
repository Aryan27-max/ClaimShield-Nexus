"""P2 exit check: recall per scheme x lens, legit-outlier ranks, runtime. Eval may read ground_truth; lenses may not.
Run: python -m eval.lens_check"""
import sys
import time

import pandas as pd

from core import anomaly, graph, rules
from core import schema as S

TOP_N, MAX_RUNTIME_S = 20, 40


def run_lenses(t: dict) -> tuple[dict, dict]:
    timings, out = {}, {}
    t0 = time.time()
    out["rules"] = rules.run_rules(t["claims"], t["members"], t["providers"], t["addresses"])
    timings["rules"] = time.time() - t0
    t0 = time.time()
    out["anomaly"], out["anomaly_scores"] = anomaly.run_anomaly(t["claims"], t["providers"])
    timings["anomaly"] = time.time() - t0
    t0 = time.time()
    out["graph"], out["graph_features"], _ = graph.run_graph(t)
    timings["graph"] = time.time() - t0
    return out, timings


def flagged_providers(out: dict, lens: str) -> set:
    a = out[lens]
    hit = set(a.entity_id[a.entity_type == "provider"])
    if lens == "graph":
        gf = out["graph_features"]
        hit |= set(gf.provider_id[gf.ring_id.isin(a.entity_id[a.entity_type == "community"])])
    return hit


def recall_table(gt: pd.DataFrame, out: dict) -> pd.DataFrame:
    lenses = ["rules", "anomaly", "graph"]
    hits = {lens: flagged_providers(out, lens) for lens in lenses}
    rows = {s: {lens: len(set(g.entity_id) & hits[lens]) / len(g) for lens in lenses} | {"n": len(g)}
            for s, g in gt.groupby("scheme")}
    tab = pd.DataFrame(rows).T[["n"] + lenses].astype({"n": int})
    tab["any"] = [len(set(g.entity_id) & set().union(*hits.values())) / len(g) for _, g in gt.groupby("scheme")]
    return tab


def outlier_ranks(lo: pd.DataFrame, out: dict) -> pd.DataFrame:
    a = out["anomaly_scores"].set_index("provider_id").score.rank(ascending=False, method="min")
    g = out["graph_features"].set_index("provider_id").graph_score.rank(ascending=False, method="min")
    return lo.assign(anomaly_rank=lo.entity_id.map(a).astype(int), graph_rank=lo.entity_id.map(g).astype(int))


def main() -> int:
    t = {n: S.load(n) for n in ["claims", "members", "providers", "addresses", "referrals", "investigations"]}
    gt, lo = S.load("ground_truth"), S.load("legit_outliers")
    out, timings = run_lenses(t)
    tab = recall_table(gt, out)
    print("Recall (planted entities hit / planted):")
    print(tab.to_string(float_format=lambda v: f"{v:.2f}"))
    ranks = outlier_ranks(lo, out)
    print("\nLegit outlier ranks (1 = most suspicious, of 1200):")
    print(ranks.groupby(["kind"]).agg(n=("entity_id", "size"), anomaly_best=("anomaly_rank", "min"),
                                      anomaly_median=("anomaly_rank", "median"), graph_best=("graph_rank", "min"),
                                      graph_median=("graph_rank", "median")).to_string())
    total = sum(timings.values())
    print("\nTimings: " + ", ".join(f"{k} {v:.1f}s" for k, v in timings.items()) + f", total {total:.1f}s")
    big = ranks[ranks.kind != "honest_error"]
    checks = {
        "upcoding caught by anomaly (>= 70%)": tab.at["upcoding", "anomaly"] >= 0.7,
        "dme_ring caught by graph (both rings)": tab.at["dme_ring", "graph"] == 1.0,
        "kickback_referral caught by graph": tab.at["kickback_referral", "graph"] == 1.0,
        f"no oncology/ER in top {TOP_N} of anomaly or graph": bool((big[["anomaly_rank", "graph_rank"]] > TOP_N).all().all()),
        f"rules + anomaly + graph < {MAX_RUNTIME_S}s": total < MAX_RUNTIME_S,
    }
    print()
    for name, ok in checks.items():
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
