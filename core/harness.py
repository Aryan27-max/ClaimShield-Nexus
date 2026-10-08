"""Decision harness: human-authored policy YAML -> allowed / recommended actions with a rule trace.
decide() is the only writer of final actions (human user_id + reason_code, ledgered)."""
import hashlib
import sqlite3
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


def _cond(key: str, v, case) -> tuple[str, bool]:
    classes, codes = list(case["classes"]), list(case["codes"])
    conf, usd, sev = float(case["confidence"]), float(case["dollars_at_risk"]), int(case["max_severity"])
    match key:
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
    ab, classes = policy["abstain"], list(case["classes"])
    missing = [c for c in EVIDENCE_CLASSES if c not in classes]
    stat_only = classes == ["statistical"]
    trace = []
    if case["completeness"] < ab["min_completeness"]:
        trace.append(f"abstain: data completeness {case['completeness']:.2f} < {ab['min_completeness']} → fail")
    if stat_only and case["fused_score"] < ab["statistical_min"]:
        trace.append(f"abstain: only statistical evidence and fused score {case['fused_score']:.2f} "
                     f"< statistical_min {ab['statistical_min']} → fail")
    if trace:
        return {"allowed_actions": list(SAFE), "recommended_action": "NEEDS_MORE_DATA", "requires_human": False,
                "rule_trace": trace + [f"{a}: blocked by abstain rule" for a in ESCALATING], "missing_classes": missing}
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
            "missing_classes": missing}


def evaluate_all(cases: pd.DataFrame, policy: dict) -> pd.DataFrame:
    ev = pd.DataFrame([evaluate(r, policy) for _, r in cases.iterrows()], index=cases.index)
    out = cases.join(ev)
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
    with _db(db) as con:
        cur = con.execute("INSERT INTO decisions (ts, case_id, action, recommended_action, user_id, reason_code, note, "
                          "policy_version, policy_hash, ledger_idx) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (datetime.now(timezone.utc).isoformat(), case_id, action, ev["recommended_action"], user_id,
                           reason_code, note, policy["version"], policy["_hash"], entry["idx"]))
    return {"decision_id": cur.lastrowid, "ledger_idx": entry["idx"], "hash": entry["hash"]}


def decisions(db=None) -> pd.DataFrame:
    with _db(db) as con:
        return pd.read_sql("SELECT * FROM decisions ORDER BY decision_id", con)
