"""P3 exit check: funnel, top queue, action matrix by ground-truth label, policy invariants, runtime.
Eval may read ground_truth / legit_outliers; the pipeline may not. Run: python -m eval.pipeline_check"""
import copy
import sys

import pandas as pd

from core import harness, pipeline
from core import queue as Q
from core import schema as S

MAX_RUNTIME_S = 60
HIGH = ["PREPAY_REVIEW", "FULL_INVESTIGATION", "REFER_TO_MFCU"]
COLS = harness.ACTIONS[::-1] + ["no_case"]


def entity_labels() -> pd.DataFrame:
    gt = S.load("ground_truth").rename(columns={"scheme": "label"})[["entity_id", "label"]]
    lo = S.load("legit_outliers").rename(columns={"kind": "label"})[["entity_id", "label"]]
    lo["label"] = lo.label.replace({"high_cost_oncology": "oncology"})
    lab = pd.concat([gt, lo]).astype(str)
    p = S.load("providers").provider_id.astype(str)
    clean = pd.DataFrame({"entity_id": p[~p.isin(lab.entity_id)], "label": "clean"})
    return pd.concat([lab, clean], ignore_index=True)


def provider_actions(cases: pd.DataFrame) -> pd.DataFrame:
    return cases[["case_id", "providers", "recommended_action", "classes"]].explode("providers") \
        .rename(columns={"providers": "entity_id"})


def action_matrix(cases: pd.DataFrame) -> pd.DataFrame:
    m = entity_labels().merge(provider_actions(cases), on="entity_id", how="left")
    m["recommended_action"] = m.recommended_action.fillna("no_case")
    mat = pd.crosstab(m.label, m.recommended_action).reindex(columns=COLS, fill_value=0)
    return mat, m


def checks(cases: pd.DataFrame, mat: pd.DataFrame, m: pd.DataFrame, policy: dict, runtime: float) -> list[tuple[str, bool]]:
    out = []
    for s in S.SCHEMES:
        out.append((f"{s}: >=1 entity at PREPAY_REVIEW+", bool(mat.loc[s, HIGH].sum() >= 1)))
    for lab in ["oncology", "busy_er", "honest_error"]:
        out.append((f"{lab}: none at FULL_INVESTIGATION/MFCU",
                    bool(mat.loc[lab, ["FULL_INVESTIGATION", "REFER_TO_MFCU"]].sum() == 0) if lab in mat.index else True))
    ca = m[(m.label == "clean") & m.classes.map(lambda c: isinstance(c, (list, tuple)) or hasattr(c, "tolist"))]
    ca = ca[ca.classes.map(lambda c: list(c) == ["statistical"])]
    safe = ca.recommended_action.isin(["NEEDS_MORE_DATA", "MONITOR"]).mean() if len(ca) else 1.0
    out.append((f"clean anomaly-only: {safe:.0%} of {len(ca)} at NEEDS_MORE_DATA/MONITOR (need >= 80%)", safe >= 0.8))
    mc, rule = cases[cases.recommended_action == "REFER_TO_MFCU"], policy["actions"]["REFER_TO_MFCU"]
    ok = ((mc.n_classes >= rule["min_classes"]) & (mc.confidence >= rule["min_conf"]) &
          (mc.dollars_at_risk >= rule["min_dollars"]) & mc.requires_human).all()
    out.append((f"MFCU ({len(mc)}) only where policy conditions hold", bool(ok)))
    gf = S.load("graph_features").dropna(subset=["ring_id"])
    pa = provider_actions(cases)
    for ring, grp in gf.groupby("ring_id"):
        n = pa[pa.entity_id.isin(grp.provider_id.astype(str))].case_id.nunique()
        out.append((f"{ring}: {len(grp)} providers -> {n} case", n == 1))
    out.append((f"pipeline runtime {runtime:.1f}s < {MAX_RUNTIME_S}s", runtime < MAX_RUNTIME_S))
    return out


def upcoding_at_prepay(cases: pd.DataFrame, policy: dict, **predictive) -> int:
    """Upcoding entities at PREPAY_REVIEW+ when re-evaluated with the given predictive thresholds."""
    pol = copy.deepcopy(policy)
    pol["predictive"].update(predictive)
    base = cases.drop(columns=harness.OUTPUT_COLS)
    mat, _ = action_matrix(harness.evaluate_all(base, pol))
    return int(mat.loc["upcoding", HIGH].sum())


def main() -> int:
    meta = pipeline.run_all()
    cases, policy = pd.read_parquet(S.CASES), harness.load_policy()
    q = Q.rank(cases, policy)
    f = meta["funnel"]
    print(f"funnel: {f['claims_flagged']:,} flagged claims -> {f['alerts']} alerts -> {f['cases']} cases "
          f"-> {int((q.status == 'in_capacity').sum())} in capacity ({q.attrs['used_hours']:.0f}/{q.attrs['capacity_hours']:.0f} h), "
          f"{int((q.status == 'deferred').sum())} deferred")
    q["cls"] = q.classes.map(lambda c: "+".join(x[:4] for x in c))
    print(q.head(15)[["rank", "case_id", "n_providers", "recommended_action", "confidence", "cls", "dollars_at_risk",
                      "members_affected", "est_hours", "priority", "status"]].to_string(index=False))
    mat, m = action_matrix(cases)
    print(mat.to_string())
    pr = policy["predictive"]
    print(f"upcoding at PREPAY+: before (no predictive lift) {upcoding_at_prepay(cases, policy, lift_min=2.0)} -> "
          f"after (policy lift_min {pr['lift_min']}, statistical_min {pr['statistical_min']}) "
          f"{upcoding_at_prepay(cases, policy)}; sensitivity lift_min 0.6 + statistical_min 0.55 -> "
          f"{upcoding_at_prepay(cases, policy, lift_min=0.6, statistical_min=0.55)}")
    res = checks(cases, mat, m, policy, meta["timings"]["total"])
    for name, ok in res:
        print(("PASS " if ok else "FAIL ") + name)
    print(f"timings: {meta['timings']}  policy {meta['policy_hash'][:12]}")
    return 0 if all(ok for _, ok in res) else 1


if __name__ == "__main__":
    sys.exit(main())
