"""P3 exit check: funnel, top queue, action matrix by ground-truth label, policy invariants, runtime.
Eval may read ground_truth / legit_outliers; the pipeline may not. Run: python -m eval.pipeline_check"""
import sys

import pandas as pd

from core import harness, pipeline
from core import queue as Q
from core import schema as S
from eval.metrics import DEMO_THRESHOLDS, HIGH, action_matrix, provider_actions, validation

MAX_RUNTIME_S = 60


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
    before, after = validation(cases), validation(harness.evaluate_all(
        cases.drop(columns=harness.OUTPUT_COLS), harness.with_thresholds(policy, DEMO_THRESHOLDS)))
    print(f"policy demo {DEMO_THRESHOLDS}: upcoding PREPAY+ {before['upcoding_prepay_plus']} -> "
          f"{after['upcoding_prepay_plus']}, clean escalated {before['clean_escalated']} -> {after['clean_escalated']}")
    res = checks(cases, mat, m, policy, meta["timings"]["total"])
    for name, ok in res:
        print(("PASS " if ok else "FAIL ") + name)
    print(f"timings: {meta['timings']}  policy {meta['policy_hash'][:12]}")
    return 0 if all(ok for _, ok in res) else 1


if __name__ == "__main__":
    sys.exit(main())
