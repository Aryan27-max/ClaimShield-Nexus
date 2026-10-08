"""Decision harness: human-authored policy YAML -> allowed / recommended actions with a rule trace.
decide() is the only writer of final actions (human user_id + reason_code, ledgered)."""
import copy
import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from core import ledger
from core import schema as S

ACTIONS = ["MONITOR", "NEEDS_MORE_DATA", "PROVIDER_EDUCATION", "PREPAY_REVIEW", "FULL_INVESTIGATION", "REFER_TO_MFCU"]
ESCALATING = ACTIONS[:1:-1]  # MFCU -> EDUCATION, checked top-down
SAFE = ["NEEDS_MORE_DATA", "MONITOR"]
EVIDENCE_CLASSES = ["deterministic", "structural", "statistical"]
OUTPUT_COLS = ["allowed_actions", "recommended_action", "rule_trace", "requires_human", "missing_classes",
               "predictive_driven", "est_hours", "policy_version", "policy_hash"]  # added by evaluate_all
DECISIONS_DDL = """CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, case_id TEXT NOT NULL, action TEXT NOT NULL,
    recommended_action TEXT, user_id TEXT NOT NULL, reason_code TEXT NOT NULL, note TEXT,
    policy_version INTEGER, policy_hash TEXT, ledger_idx INTEGER)"""


def load_policy(path: Path | str | None = None) -> dict:
    """Parsed policy plus `_hash` (sha256 of the YAML bytes) and `_path`."""
    p = Path(path or S.POLICY)
    raw = p.read_bytes()
    pol = yaml.safe_load(raw)
    pol["_hash"], pol["_path"] = hashlib.sha256(raw).hexdigest(), str(p)
    return pol


PREDICTIVE_NOTE = "Recommendation relies on the predictive model plus peer comparison; no rule or network evidence."


def _lift(case, pr: dict) -> tuple[str, bool]:
    sp, ss = float(case.get("score_predictive", 0.0)), float(case["score_statistical"])
    ok = list(case["classes"]) == ["statistical"] and sp >= pr["lift_min"] and ss >= pr["statistical_min"]
    return (f"predictive lift: statistical-only, p_fwa(90) {sp:.2f} >= {pr['lift_min']} & "
            f"statistical {ss:.2f} >= {pr['statistical_min']}", ok)


def _cond(key: str, v, case) -> tuple[str, bool]:
    classes, codes = list(case["classes"]), list(case["codes"])
    conf, usd, sev = float(case["confidence"]), float(case["dollars_at_risk"]), int(case["max_severity"])
    match key:
        case "predictive_lift":
            return _lift(case, case["_pred"])
        case "min_classes":
            return f"evidence classes {len(classes)} >= {v}", len(classes) >= v
        case "min_conf":
            return f"confidence {conf:.2f} >= {v}", conf >= v
        case "min_dollars":
            return f"$ at risk {usd:,.0f} >= {v:,}", usd >= v
        case "max_dollars":
            return f"$ at risk {usd:,.0f} <= {v:,}", usd <= v
        case "min_severity":
            return f"severity {sev} >= {v}", sev >= v
        case "max_severity":
            return f"severity {sev} <= {v}", sev <= v
        case "classes_any":
            return f"has class in {v} (has {classes})", bool(set(v) & set(classes))
        case "classes_all":
            return f"has all classes {v} (has {classes})", set(v) <= set(classes)
        case "codes_any":
            return f"alert code in {v}", bool(set(v) & set(codes))
        case "min_class_score":
            parts = [(f"{c} score {float(case[f'score_{c}']):.2f} >= {x}", float(case[f"score_{c}"]) >= x)
                     for c, x in v.items()]
            return " & ".join(d for d, _ in parts), all(p for _, p in parts)
    raise KeyError(f"unknown policy condition {key}")


def _check(cond: dict, case) -> list[tuple[str, bool]]:
    out = []
    for k, v in cond.items():
        if k == "requires_human":
            continue
        if k == "any_of":
            subs = [_check(c, case) for c in v]
            ok = [all(p for _, p in s) for s in subs]
            desc = " OR ".join("(" + ", ".join(d for d, _ in s) + (" ✓" if o else " ✗") + ")" for s, o in zip(subs, ok))
            out.append((f"any of {desc}", any(ok)))
        else:
            out.append(_cond(k, v, case))
    return out


def est_hours(action: str, n_providers: int, policy: dict) -> float:
    eh = policy["est_hours"]
    return float(eh[action] + eh["per_extra_provider"] * (n_providers - 1)) if eh[action] else 0.0


def evaluate(case, policy: dict) -> dict:
    """allowed_actions (high -> low), recommended_action, rule_trace (why not higher), missing_classes."""
    case = {**dict(case), "_pred": policy.get("predictive", {"lift_min": 2.0, "statistical_min": 2.0})}
    ab, classes = policy["abstain"], list(case["classes"])
    missing = [c for c in EVIDENCE_CLASSES if c not in classes]
    stat_only = classes == ["statistical"]
    lift_desc, lift = _lift(case, case["_pred"])
    trace = []
    if case["completeness"] < ab["min_completeness"]:
        trace.append(f"abstain: data completeness {case['completeness']:.2f} < {ab['min_completeness']} → fail")
    if stat_only and case["fused_score"] < ab["statistical_min"] and lift:
        trace.append(f"abstain bypassed by {lift_desc} → pass")
    elif stat_only and case["fused_score"] < ab["statistical_min"]:
        trace.append(f"abstain: only statistical evidence and fused score {case['fused_score']:.2f} "
                     f"< statistical_min {ab['statistical_min']} → fail")
    if any(t.startswith("abstain:") for t in trace):
        return {"allowed_actions": list(SAFE), "recommended_action": "NEEDS_MORE_DATA", "requires_human": False,
                "rule_trace": trace + [f"{a}: blocked by abstain rule" for a in ESCALATING], "missing_classes": missing,
                "predictive_driven": False}
    allowed = []
    for a in ESCALATING:
        checks = _check(policy["actions"][a], case)
        if not allowed:
            trace += [f"{a}: {d} → {'pass' if p else 'fail'}" for d, p in checks]
        if all(p for _, p in checks):
            allowed.append(a)
    rec = allowed[0] if allowed else ("NEEDS_MORE_DATA" if stat_only else "MONITOR")
    if not allowed:
        trace.append(f"no escalating action passed → {rec}")
    return {"allowed_actions": allowed + SAFE, "recommended_action": rec, "rule_trace": trace,
            "requires_human": any(policy["actions"][a].get("requires_human", False) for a in allowed),
            "missing_classes": missing, "predictive_driven": bool(lift and rec == "PREPAY_REVIEW")}


def evaluate_all(cases: pd.DataFrame, policy: dict) -> pd.DataFrame:
    ev = pd.DataFrame([evaluate(r, policy) for _, r in cases.iterrows()], index=cases.index)
    out = cases.join(ev)
    out["limitations"] = [[x for x in lim if x != PREDICTIVE_NOTE] + ([PREDICTIVE_NOTE] if drv else [])
                          for lim, drv in zip(out.limitations, out.predictive_driven)]
    out["est_hours"] = [est_hours(a, n, policy) for a, n in zip(out.recommended_action, out.n_providers)]
    out["policy_version"], out["policy_hash"] = policy["version"], policy["_hash"]
    return out


def _db(db) -> sqlite3.Connection:
    con = sqlite3.connect(Path(db or S.LEDGER_DB))
    con.execute(DECISIONS_DDL)
    return con


def decide(case_id: str, action: str, user_id: str, reason_code: str, note: str = "",
           cases: pd.DataFrame | None = None, policy: dict | None = None, db=None) -> dict:
    """The ONLY writer of final actions. Re-checks the case against the policy; raises ValueError if invalid."""
    policy = policy or load_policy()
    cases = cases if cases is not None else pd.read_parquet(S.CASES)
    row = cases[cases.case_id == case_id]
    if row.empty:
        raise ValueError(f"unknown case {case_id}")
    if not str(user_id or "").strip():
        raise ValueError("user_id is required")
    if reason_code not in policy["reason_codes"]:
        raise ValueError(f"reason_code must be one of {list(policy['reason_codes'])}")
    if reason_code == "OTHER" and not str(note or "").strip():
        raise ValueError("note is required when reason_code is OTHER")
    ev = evaluate(row.iloc[0], policy)
    if action not in ev["allowed_actions"]:
        raise ValueError(f"{action} is not allowed for {case_id}; allowed: {ev['allowed_actions']}")
    payload = {"case_id": case_id, "action": action, "recommended_action": ev["recommended_action"],
               "allowed_actions": ev["allowed_actions"], "user_id": user_id, "reason_code": reason_code,
               "note": note, "confidence": float(row.iloc[0].confidence),
               "policy_version": policy["version"], "policy_hash": policy["_hash"]}
    entry = ledger.append(f"human:{user_id}", "human_decision", payload, db)
    with closing(_db(db)) as con, con:
        cur = con.execute("INSERT INTO decisions (ts, case_id, action, recommended_action, user_id, reason_code, note, "
                          "policy_version, policy_hash, ledger_idx) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (datetime.now(timezone.utc).isoformat(), case_id, action, ev["recommended_action"], user_id,
                           reason_code, note, policy["version"], policy["_hash"], entry["idx"]))
    return {"decision_id": cur.lastrowid, "ledger_idx": entry["idx"], "hash": entry["hash"]}


def decisions(db=None) -> pd.DataFrame:
    with closing(_db(db)) as con:
        return pd.read_sql("SELECT * FROM decisions ORDER BY decision_id", con)


THRESHOLDS = {  # dotted policy path -> label shown on the Policy page
    "abstain.statistical_min": "Abstain: statistical-only fused score below",
    "actions.PREPAY_REVIEW.any_of.1.min_class_score.statistical": "E/M upcoding path: statistical score floor",
    "actions.PREPAY_REVIEW.any_of.1.min_conf": "E/M upcoding path: min confidence",
    "predictive.lift_min": "Predictive lift: p_fwa(90) at least",
    "predictive.statistical_min": "Predictive lift: statistical score floor",
    "actions.FULL_INVESTIGATION.min_conf": "FULL_INVESTIGATION: min confidence",
    "actions.REFER_TO_MFCU.min_conf": "REFER_TO_MFCU: min confidence",
    "actions.REFER_TO_MFCU.min_dollars": "REFER_TO_MFCU: min $ at risk",
    "capacity.hours_per_investigator_week": "Hours per investigator per week",
}


def _walk(d, path: str):
    *head, last = path.split(".")
    for k in head:
        d = d[int(k)] if isinstance(d, list) else d[k]
    return d, (int(last) if isinstance(d, list) else last)


def get_threshold(policy: dict, path: str):
    d, k = _walk(policy, path)
    return d[k]


def with_thresholds(policy: dict, values: dict) -> dict:
    """Unsaved copy of the policy with dotted-path thresholds replaced; `_hash` is provisional (preview only)."""
    pol = copy.deepcopy({k: v for k, v in policy.items() if not k.startswith("_")})
    for path, v in values.items():
        d, k = _walk(pol, path)
        d[k] = v
    pol["_hash"] = hashlib.sha256(yaml.safe_dump(pol, sort_keys=True).encode()).hexdigest()
    pol["_path"] = "(unsaved preview)"
    return pol


def diff(cases: pd.DataFrame, old: dict, new: dict) -> pd.DataFrame:
    """Cases whose recommended action changes between two policies, with the first new rule-trace line as `why`."""
    base = cases.drop(columns=OUTPUT_COLS, errors="ignore")
    a, b = evaluate_all(base, old), evaluate_all(base, new)
    ch = a.recommended_action != b.recommended_action
    why = [next((t for t in nt if t not in set(ot)), nt[0] if len(nt) else "")
           for ot, nt in zip(a.rule_trace[ch], b.rule_trace[ch])]
    return pd.DataFrame({"case_id": a.case_id[ch], "before": a.recommended_action[ch],
                         "after": b.recommended_action[ch], "why": why})


def save_version(policy: dict, author: str, reason: str, old: dict, folder: Path | str | None = None, db=None) -> dict:
    """Writes policy/harness_vN.yaml (N = next free version; never overwrites) and a `policy_change` ledger block."""
    if not str(author).strip() or not str(reason).strip():
        raise ValueError("author and change reason are required")
    folder = Path(folder or Path(S.POLICY).parent)
    n = 1 + max(int(p.stem.rsplit("v", 1)[-1]) for p in folder.glob("harness_v*.yaml"))
    path = folder / f"harness_v{n}.yaml"
    body = {**{k: v for k, v in policy.items() if not k.startswith("_")}, "version": n, "name": f"harness_v{n}",
            "author": author, "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "change_reason": reason,
            "parent_hash": old["_hash"]}
    with open(path, "x") as f:
        f.write("# Human-authored decision policy. Models propose; this policy constrains; a human decides.\n")
        yaml.safe_dump(body, f, sort_keys=False, allow_unicode=True)
    new = load_policy(path)
    entry = ledger.append(f"human:{author}", "policy_change", {
        "old_version": old["version"], "old_hash": old["_hash"], "new_version": n, "new_hash": new["_hash"],
        "path": path.name, "author": author, "reason": reason}, db)
    return {"path": str(path), "hash": new["_hash"], "version": n, "ledger_idx": entry["idx"]}
