"""run_all(): rules -> anomaly -> graph -> snapshots + predict -> fusion -> harness -> data/out/cases.parquet + ledger batch entries.
Run: python -m core.pipeline [--reset-ledger]"""
import argparse
import hashlib
import json
import time

import pandas as pd

from core import anomaly, fusion, graph, harness, ledger, predict, rules, snapshots
from core import queue as Q
from core import schema as S

TABLES = ["claims", "members", "providers", "addresses", "referrals", "investigations"]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def case_hash(r) -> str:
    body = {"case_id": r.case_id, "providers": list(r.providers), "classes": list(r.classes),
            "confidence": float(r.confidence), "dollars_at_risk": float(r.dollars_at_risk),
            "recommended_action": r.recommended_action, "allowed_actions": list(r.allowed_actions),
            "claims_sha": _sha(",".join(r.flagged_claim_ids))}
    return _sha(json.dumps(body, sort_keys=True))


def merkle_root(leaves: list[str]) -> str:
    level = leaves or [_sha("")]
    while len(level) > 1:
        if len(level) % 2:
            level = level + level[-1:]
        level = [_sha(a + b) for a, b in zip(level[::2], level[1::2])]
    return level[0]


def _log_rules(alerts: pd.DataFrame, runtime_s: float) -> None:
    ledger.append("system:rules", "lens_run", {
        "lens": "rules", "n_alerts": len(alerts), "by_code": alerts.code.value_counts().sort_index().to_dict(),
        "n_claims": int(alerts.claim_ids.map(len).sum()), "dollars_at_risk": round(float(alerts.dollars_at_risk.sum()), 2),
        "alerts_sha": _sha(",".join(sorted(alerts.alert_id))), "runtime_s": round(runtime_s, 2)})


def run_all(reset_ledger: bool = False, policy_path=None) -> dict:
    """Runs every lens + fusion + harness; writes alerts, cases and run_meta; returns run_meta."""
    if reset_ledger:
        ledger.reset()
    t0 = time.time()
    t = {n: S.load(n) for n in TABLES}
    timings = {"load": time.time() - t0}

    t1 = time.time()
    ar = rules.run_rules(t["claims"], t["members"], t["providers"], t["addresses"])
    timings["rules"] = time.time() - t1
    t1 = time.time()
    aa, sc = anomaly.run_anomaly(t["claims"], t["providers"])
    timings["anomaly"] = time.time() - t1
    t1 = time.time()
    ag, gf, _ = graph.run_graph(t)
    timings["graph"] = time.time() - t1
    for name, df in [("alerts_rules", ar), ("alerts_anomaly", aa), ("alerts_graph", ag), ("graph_features", gf)]:
        df.to_parquet(S.OUT / f"{name}.parquet", index=False)
    _log_rules(ar, timings["rules"])
    anomaly.log_run(aa, sc, timings["anomaly"])
    graph.log_run(ag, gf, timings["graph"])

    alerts = pd.concat([ar, aa, ag], ignore_index=True)
    t1 = time.time()
    snap = snapshots.build(t, ar, alerts)
    snap.to_parquet(S.OUT / "snapshots.parquet", index=False)
    timings["snapshots"] = time.time() - t1
    t1 = time.time()
    preds, report = predict.run_predict(snap)
    preds.to_parquet(S.OUT / "predictions.parquet", index=False)
    timings["predict"] = time.time() - t1
    predict.log_run(report, timings["predict"])

    t1 = time.time()
    policy = harness.load_policy(policy_path)
    cases = harness.evaluate_all(fusion.build_cases(alerts, t, gf, policy, preds), policy)
    cases.to_parquet(S.CASES, index=False)
    timings["fusion_harness"] = time.time() - t1

    leaves = [case_hash(r) for r in cases.sort_values("case_id").itertuples()]
    meta = {"funnel": fusion.funnel(alerts, cases),
            "actions": cases.recommended_action.value_counts().to_dict(),
            "policy_version": policy["version"], "policy_hash": policy["_hash"], "policy_path": policy["_path"],
            "cases_merkle_root": merkle_root(leaves), "n_cases": len(cases),
            "model_params_hash": predict.params_hash(), "model_test": {h: r["test"] for h, r in report.items()},
            "predictive_available": Q.PREDICTIVE_AVAILABLE, "asof": str(S.END.date())}
    entry = ledger.append("system:pipeline", "fusion_run", meta)
    timings["total"] = time.time() - t0
    meta.update(ledger_idx=entry["idx"], timings={k: round(v, 2) for k, v in timings.items()})
    S.RUN_META.write_text(json.dumps(meta, indent=1, default=str))
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-ledger", action="store_true", help="dev: start a fresh ledger before logging")
    meta = run_all(ap.parse_args().reset_ledger)
    print(json.dumps({k: meta[k] for k in ["funnel", "actions", "policy_hash", "cases_merkle_root", "timings"]}, indent=1))
    print(f"ledger verify = {ledger.verify()}")


if __name__ == "__main__":
    main()
