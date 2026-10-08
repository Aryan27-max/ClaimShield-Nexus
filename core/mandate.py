"""Signed mandates (AP2-inspired, for enforcement): policy = intent mandate signed by an SIU lead, decision = cart
mandate bound to case / evidence / policy hashes, execution = second signature (dual control, four-eyes).
Canonical JSON (sorted keys, no whitespace) -> SHA-256 -> Ed25519. Stored in `mandates` and as ledger blocks."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core import identity, ledger
from core import schema as S
from core.policy_schema import ACTIONS

EVENTS = {"policy": "policy_mandate", "decision": "decision_mandate", "execution": "execution_mandate",
          "revocation": "revocation"}
SIGNER = {"policy": "issuer", "decision": "signer", "execution": "approver", "revocation": "signer"}
SIG_FIELDS = ("mandate_hash", "signature", "fingerprint", "alg")
DDL = """CREATE TABLE IF NOT EXISTS mandates (hash TEXT PRIMARY KEY, type TEXT NOT NULL, case_id TEXT, ref TEXT,
    signer TEXT NOT NULL, ts TEXT NOT NULL, block_json TEXT NOT NULL, ledger_idx INTEGER)"""


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign(payload: dict) -> dict:
    """Signed block = payload + mandate_hash + signature + key fingerprint + algorithm."""
    signer = payload[SIGNER[payload["type"]]]
    h = digest(payload)
    return {**payload, "mandate_hash": h, "signature": identity.sign(signer, h.encode()),
            "fingerprint": identity.registry()[signer]["fingerprint"], "alg": identity.ALG}


def verify(block: dict | None) -> bool:
    """Recomputes the hash over everything except the signature fields, then checks the signer's key."""
    if not block or block.get("type") not in SIGNER:
        return False
    payload = {k: v for k, v in block.items() if k not in SIG_FIELDS}
    h = digest(payload)
    return h == block.get("mandate_hash") and identity.verify(
        payload.get(SIGNER[block["type"]]), h.encode(), block.get("signature", ""), block.get("fingerprint"))


def _db(db) -> sqlite3.Connection:
    con = sqlite3.connect(Path(db or ledger.LEDGER_DB))  # same file the ledger writes to
    con.execute(DDL)
    return con


def store(block: dict, db=None) -> int:
    """Ledger block (signed payload + signature + fingerprint) and an index row; returns the ledger idx."""
    t, signer = block["type"], block[SIGNER[block["type"]]]
    actor = "system:automation" if identity.role(signer) == "automation" else f"human:{signer}"
    entry = ledger.append(actor, EVENTS[t], block, db)
    ref = block.get("policy_hash") or block.get("decision_mandate_hash") or block.get("target_hash")
    with closing(_db(db)) as con, con:
        con.execute("INSERT OR REPLACE INTO mandates VALUES (?,?,?,?,?,?,?,?)",
                    (block["mandate_hash"], t, block.get("case_id"), ref, signer, block.get("ts") or
                     block.get("issued_at") or _now(), json.dumps(block), entry["idx"]))
    return entry["idx"]


def mandates(db=None) -> pd.DataFrame:
    with closing(_db(db)) as con:
        return pd.read_sql("SELECT * FROM mandates ORDER BY ledger_idx", con)


def get(h: str, db=None) -> dict | None:
    m = mandates(db)
    row = m[m.hash == h]
    return json.loads(row.block_json.iloc[0]) if len(row) else None


def revoked(h: str, db=None) -> bool:
    m = mandates(db)
    return bool(((m.type == "revocation") & (m.ref == h)).any())


def _require_role(user: str, roles: set, what: str) -> None:
    r = identity.role(user)
    if r not in roles:
        raise ValueError(f"{user} ({r or 'unknown identity'}) may not {what}")


def issue_policy(policy: dict, issuer: str, parent_hash: str | None = None, db=None) -> dict:
    """Intent mandate: an SIU lead authorises this exact policy version and its automation / dual-control scope."""
    _require_role(issuer, {"siu_lead"}, "sign a policy")
    block = sign({"type": "policy", "policy_version": policy["version"], "policy_hash": policy["_hash"],
                  "parent_hash": parent_hash or policy.get("parent_hash"), "issuer": issuer,
                  "scope": {"allowed_actions": ACTIONS, "dual_control_actions": policy.get("dual_control_actions", []),
                            "automation_scope": policy.get("automation_scope", [])}, "issued_at": _now()})
    store(block, db)
    return block


def policy_status(policy: dict, db=None) -> tuple[bool, str, dict | None]:
    """(authorised, reason, mandate) for the policy version in force. Missing / invalid / revoked => not authorised."""
    m = mandates(db)
    rows = m[(m.type == "policy") & (m.ref == policy["_hash"])]
    if rows.empty:
        return False, "no signed policy mandate for this version", None
    block = json.loads(rows.block_json.iloc[-1])
    if revoked(block["mandate_hash"], db):
        return False, f"policy mandate revoked ({block['mandate_hash'][:12]})", block
    if not verify(block) or identity.role(block["issuer"]) != "siu_lead":
        return False, "policy mandate signature invalid", block
    return True, f"signed by {block['issuer']} · key {block['fingerprint']}", block


def case_hash(case) -> str:
    c = dict(case)
    return digest({"case_id": c["case_id"], "providers": list(c["providers"]), "classes": list(c["classes"]),
                   "confidence": float(c["confidence"]), "dollars_at_risk": float(c["dollars_at_risk"]),
                   "claims_sha": hashlib.sha256(",".join(c["flagged_claim_ids"]).encode()).hexdigest()})


def evidence_hash(case) -> str:
    c = dict(case)
    return digest({"alert_ids": list(c["alert_ids"]), "codes": list(c["codes"]), "evidence": list(c["evidence"])})


def note_sha(note: str | None) -> str:
    return hashlib.sha256(str(note or "").encode()).hexdigest()


def sign_decision(case, policy: dict, action: str, reason_code: str, note: str, signer: str,
                  amount: float | None = None) -> dict:
    """Cart mandate signed by the deciding person, bound to the live case, evidence and policy."""
    c = dict(case)
    return sign({"type": "decision", "case_id": c["case_id"], "case_hash": case_hash(c), "evidence_hash": evidence_hash(c),
                 "policy_hash": policy["_hash"], "action": action, "reason_code": reason_code, "note_sha": note_sha(note),
                 "amount": amount, "signer": signer, "role": identity.role(signer), "ts": _now()})


def check_decision(block: dict | None, case, policy: dict, action: str, reason_code: str, note: str, user_id: str,
                   amount: float | None = None) -> None:
    """Raises ValueError unless the signed decision matches the live case, evidence, policy and request."""
    if not block:
        raise ValueError("unsigned decision: a signed decision mandate is required")
    if block.get("type") != "decision" or not verify(block):
        raise ValueError("decision mandate signature invalid")
    _require_role(user_id, {"investigator", "siu_lead", "automation"}, "decide cases")
    if block["signer"] != user_id:
        raise ValueError("decision mandate signer does not match the deciding user")
    c = dict(case)
    live = {"case_id": c["case_id"], "case_hash": case_hash(c), "evidence_hash": evidence_hash(c),
            "policy_hash": policy["_hash"], "action": action, "reason_code": reason_code, "note_sha": note_sha(note),
            "amount": amount}
    bad = [k for k, v in live.items() if block.get(k) != v]
    if bad:
        raise ValueError(f"decision mandate does not match the live case / policy: {', '.join(bad)}")
    if identity.role(user_id) == "automation" and action not in policy.get("automation_scope", []):
        raise ValueError(f"automation may only route {policy.get('automation_scope', [])} (default-deny)")


def approve(decision_id: int, approver: str, policy: dict, db=None, asof=None) -> dict:
    """Execution mandate: a second SIU lead (not the decision signer) signs; only then the decision is EXECUTED."""
    from core import harness
    d = harness.decisions(db)
    row = d[d.decision_id == decision_id]
    if row.empty or row.status.iloc[0] != "PENDING_APPROVAL":
        raise ValueError(f"decision {decision_id} is not pending approval")
    dm = get(row.decision_mandate_hash.iloc[0], db)
    if not verify(dm):
        raise ValueError("decision mandate signature invalid")
    if revoked(dm["mandate_hash"], db):
        raise ValueError("decision was revoked")
    _require_role(approver, {"siu_lead"}, "approve (second signature)")
    if approver == dm["signer"]:
        raise ValueError("four-eyes: the approver must differ from the decision signer")
    ok, why, _ = policy_status(policy, db)
    if not ok or dm["policy_hash"] != policy["_hash"]:
        raise ValueError(f"policy not authorised for this decision: {why}")
    block = sign({"type": "execution", "decision_mandate_hash": dm["mandate_hash"], "case_id": dm["case_id"],
                  "approver": approver, "role": "siu_lead", "ts": _now()})
    idx = store(block, db)
    with closing(harness._db(db)) as con, con:
        con.execute("UPDATE decisions SET status='EXECUTED', execution_mandate_hash=? WHERE decision_id=?",
                    (block["mandate_hash"], int(decision_id)))
    return {"ledger_idx": idx, "mandate_hash": block["mandate_hash"], "status": "EXECUTED"}


def revoke(target_hash: str, reason: str, signer: str, db=None) -> dict:
    """An SIU lead revokes a pending decision or a policy version; executed decisions cannot be revoked."""
    from core import harness
    _require_role(signer, {"siu_lead"}, "revoke mandates")
    if not str(reason).strip():
        raise ValueError("a revocation reason is required")
    target = get(target_hash, db)
    if not target or target["type"] not in ("decision", "policy"):
        raise ValueError("only a decision or policy mandate can be revoked")
    d = harness.decisions(db)
    if target["type"] == "decision":
        row = d[d.decision_mandate_hash == target_hash]
        if row.empty or row.status.iloc[0] != "PENDING_APPROVAL":
            raise ValueError("only a pending decision can be revoked")
    block = sign({"type": "revocation", "target_hash": target_hash, "target_type": target["type"],
                  "case_id": target.get("case_id"), "reason": reason, "signer": signer, "ts": _now()})
    idx = store(block, db)
    if target["type"] == "decision":
        with closing(harness._db(db)) as con, con:
            con.execute("UPDATE decisions SET status='REVOKED' WHERE decision_mandate_hash=?", (target_hash,))
    return {"ledger_idx": idx, "mandate_hash": block["mandate_hash"]}


def verify_chain(case_id: str, db=None) -> list[dict]:
    """Latest decision of a case: execution -> decision -> policy, each with signature and link checks."""
    m = mandates(db)
    dec = m[(m.type == "decision") & (m.case_id == case_id)]
    if dec.empty:
        return []
    d = json.loads(dec.block_json.iloc[-1])
    ex = m[(m.type == "execution") & (m.ref == d["mandate_hash"])]
    pol = m[(m.type == "policy") & (m.ref == d["policy_hash"])]
    out = []
    if len(ex):
        e = json.loads(ex.block_json.iloc[-1])
        out.append({"step": "approval", "block": e, "signature_ok": verify(e), "links_ok": e["approver"] != d["signer"]})
    out.append({"step": "decision", "block": d, "signature_ok": verify(d), "links_ok": not revoked(d["mandate_hash"], db)})
    p = json.loads(pol.block_json.iloc[-1]) if len(pol) else None
    out.append({"step": "policy", "block": p, "signature_ok": verify(p),
                "links_ok": bool(p) and not revoked(p["mandate_hash"], db)})
    return out


def verify_signatures(db=None) -> pd.DataFrame:
    """Re-verifies every signed block as stored in the ledger (a tampered block fails here and in verify())."""
    lg = ledger.read(db)
    rows = []
    for r in lg[lg.event_type.isin(EVENTS.values())].itertuples():
        b = json.loads(r.payload_json)
        rows.append({"idx": r.idx, "event_type": r.event_type, "signer": b.get(SIGNER.get(b.get("type"), ""), "?"),
                     "fingerprint": b.get("fingerprint", ""), "signature_ok": verify(b)})
    return pd.DataFrame(rows, columns=["idx", "event_type", "signer", "fingerprint", "signature_ok"])
