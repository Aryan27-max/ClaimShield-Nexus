import json

import pandas as pd
import pytest

from core import harness, identity, ledger
from core import mandate as M
from core import schema as S

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture(scope="module")
def cases():
    pol = harness.load_policy()
    return harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol)


def _pick(cases, action):
    return cases[cases.recommended_action == action].iloc[0]


def _decide(signed, cases, case, action, user, reason="EVIDENCE_CORROBORATED", note="", signer=None, **kw):
    pol = kw.pop("policy", signed["policy"])
    m = kw.pop("mandate", None) or M.sign_decision(case, pol, action, reason, note, signer or user)
    return harness.decide(case.case_id, action, user, reason, note, cases=kw.pop("live", cases), policy=pol,
                          db=signed["db"], mandate=m, asof="2026-10-09", **kw)


def test_sign_verify_round_trip_and_tamper(signed, cases):
    m = M.sign_decision(_pick(cases, "PREPAY_REVIEW"), signed["policy"], "PREPAY_REVIEW", "EVIDENCE_CORROBORATED", "",
                        "inv.a")
    assert M.verify(m) and m["alg"] == "Ed25519" and m["fingerprint"] == identity.registry()["inv.a"]["fingerprint"]
    assert not M.verify({**m, "action": "MONITOR"})
    assert M.canonical({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_wrong_key_fails(signed, cases):
    m = M.sign_decision(_pick(cases, "PREPAY_REVIEW"), signed["policy"], "PREPAY_REVIEW", "EVIDENCE_CORROBORATED", "",
                        "inv.a")
    payload = {k: v for k, v in m.items() if k not in M.SIG_FIELDS} | {"signer": "inv.b"}
    forged = {**payload, "mandate_hash": M.digest(payload), "signature": m["signature"],
              "fingerprint": identity.registry()["inv.b"]["fingerprint"], "alg": "Ed25519"}
    assert not M.verify(forged)
    assert not M.verify({**m, "fingerprint": identity.registry()["inv.b"]["fingerprint"]})


def test_decision_rejected_when_bindings_do_not_match(signed, cases):
    case = _pick(cases, "PREPAY_REVIEW")
    m = M.sign_decision(case, signed["policy"], "PREPAY_REVIEW", "EVIDENCE_CORROBORATED", "", "inv.a")
    moved = cases.copy()
    moved.loc[moved.case_id == case.case_id, "dollars_at_risk"] += 1
    with pytest.raises(ValueError, match="case_hash"):
        _decide(signed, cases, case, "PREPAY_REVIEW", "inv.a", mandate=m, live=moved)
    other_ev = cases.copy()
    i = other_ev.index[other_ev.case_id == case.case_id][0]
    other_ev.at[i, "evidence"] = list(other_ev.at[i, "evidence"])[:-1]
    with pytest.raises(ValueError, match="evidence_hash"):
        _decide(signed, cases, case, "PREPAY_REVIEW", "inv.a", mandate=m, live=other_ev)
    from core import policy_edit as PE
    p2 = PE.with_thresholds(signed["policy"], {"abstain.statistical_min": 0.5})
    M.issue_policy(p2, "siu.lead", db=signed["db"])
    with pytest.raises(ValueError, match="policy_hash"):
        _decide(signed, cases, case, "PREPAY_REVIEW", "inv.a", mandate=m, policy=p2)
    with pytest.raises(ValueError, match="action"):
        _decide(signed, cases, case, "PROVIDER_EDUCATION" if "PROVIDER_EDUCATION" in case.allowed_actions
                else "NEEDS_MORE_DATA", "inv.a", mandate=m)
    assert harness.decisions(signed["db"]).empty


@pytest.mark.parametrize("user, signer, mandate, error", [
    ("inv.a", "inv.a", "none", "unsigned"), ("auditor", "auditor", "sign", "may not decide"),
    ("inv.a", "inv.b", "sign", "signer does not match")])
def test_unsigned_auditor_and_impersonation_rejected(signed, cases, user, signer, mandate, error):
    case = _pick(cases, "PREPAY_REVIEW")
    m = None if mandate == "none" else M.sign_decision(case, signed["policy"], "PREPAY_REVIEW", "EVIDENCE_CORROBORATED",
                                                       "", signer)
    with pytest.raises(ValueError, match=error):
        harness.decide(case.case_id, "PREPAY_REVIEW", user, "EVIDENCE_CORROBORATED", "", cases=cases,
                       policy=signed["policy"], db=signed["db"], mandate=m)


def test_action_outside_allowed_rejected(signed, cases):
    case = _pick(cases, "PREPAY_REVIEW")
    with pytest.raises(ValueError, match="not allowed"):
        _decide(signed, cases, case, "REFER_TO_MFCU", "inv.a")


def test_system_actor_limited_to_automation_scope(signed, cases):
    case = _pick(cases, "PREPAY_REVIEW")
    with pytest.raises(ValueError, match="automation may only route"):
        _decide(signed, cases, case, "PREPAY_REVIEW", "system")
    out = _decide(signed, cases, case, "NEEDS_MORE_DATA", "system", reason="INSUFFICIENT_EVIDENCE")
    assert out["status"] == "EXECUTED"
    assert ledger.read(signed["db"]).actor.iloc[-1] == "system:automation"


def test_dual_control_four_eyes(signed, cases):
    case = _pick(cases, "REFER_TO_MFCU")
    out = _decide(signed, cases, case, "REFER_TO_MFCU", "inv.a")
    assert out["status"] == "PENDING_APPROVAL" and "obligations" not in out
    did, pol, db = out["decision_id"], signed["policy"], signed["db"]
    with pytest.raises(ValueError, match="may not approve"):
        M.approve(did, "inv.a", pol, db=db)
    with pytest.raises(ValueError, match="may not approve"):
        M.approve(did, "inv.b", pol, db=db)
    assert harness.decisions(db).status.iloc[-1] == "PENDING_APPROVAL"
    ok = M.approve(did, "siu.lead", pol, db=db, asof="2026-10-09")
    assert ok["status"] == "EXECUTED" and harness.decisions(db).status.iloc[-1] == "EXECUTED"
    chain = M.verify_chain(case.case_id, db)
    assert [c["step"] for c in chain] == ["approval", "decision", "policy"]
    assert all(c["signature_ok"] and c["links_ok"] for c in chain)
    with pytest.raises(ValueError, match="not pending"):
        M.approve(did, "siu.lead", pol, db=db)


def test_lead_cannot_approve_own_decision(signed, cases):
    out = _decide(signed, cases, _pick(cases, "REFER_TO_MFCU"), "REFER_TO_MFCU", "siu.lead")
    with pytest.raises(ValueError, match="four-eyes"):
        M.approve(out["decision_id"], "siu.lead", signed["policy"], db=signed["db"])


def test_revoked_decision_cannot_be_approved(signed, cases):
    out = _decide(signed, cases, _pick(cases, "REFER_TO_MFCU"), "REFER_TO_MFCU", "inv.a")
    with pytest.raises(ValueError, match="may not revoke"):
        M.revoke(out["mandate_hash"], "wrong case", "inv.b", db=signed["db"])
    M.revoke(out["mandate_hash"], "wrong case", "siu.lead", db=signed["db"])
    assert harness.decisions(signed["db"]).status.iloc[-1] == "REVOKED"
    with pytest.raises(ValueError, match="not pending"):
        M.approve(out["decision_id"], "siu.lead", signed["policy"], db=signed["db"])


def test_missing_invalid_or_revoked_policy_refuses_everything(signed, cases, tmp_path):
    case = _pick(cases, "PREPAY_REVIEW")
    with pytest.raises(ValueError, match="Policy not authorised"):
        harness.decide(case.case_id, "MONITOR", "inv.a", "INSUFFICIENT_EVIDENCE", "", cases=cases,
                       policy=signed["policy"], db=tmp_path / "unsigned.db",
                       mandate=M.sign_decision(case, signed["policy"], "MONITOR", "INSUFFICIENT_EVIDENCE", "", "inv.a"))
    ok, _, pm = M.policy_status(signed["policy"], signed["db"])
    assert ok
    with pytest.raises(ValueError, match="sign a policy"):
        M.issue_policy(signed["policy"], "inv.a", db=signed["db"])
    M.revoke(pm["mandate_hash"], "superseded", "siu.lead", db=signed["db"])
    assert not M.policy_status(signed["policy"], signed["db"])[0]
    for action in ("MONITOR", "PREPAY_REVIEW"):
        with pytest.raises(ValueError, match="Policy not authorised"):
            _decide(signed, cases, case, action, "inv.a")


def test_tampered_policy_mandate_is_invalid(signed):
    import sqlite3
    pol = signed["policy"]
    pm = M.policy_status(pol, signed["db"])[2]
    bad = {**pm, "scope": {**pm["scope"], "automation_scope": ["REFER_TO_MFCU"]}}
    with sqlite3.connect(signed["db"]) as con:
        con.execute("UPDATE mandates SET block_json=? WHERE hash=?", (json.dumps(bad), pm["mandate_hash"]))
    ok, why, _ = M.policy_status(pol, signed["db"])
    assert not ok and "signature invalid" in why


def test_tamper_fails_chain_and_signature_at_same_block(signed, cases):
    out = _decide(signed, cases, _pick(cases, "PREPAY_REVIEW"), "PREPAY_REVIEW", "inv.a")
    sigs = M.verify_signatures(signed["db"])
    assert sigs.signature_ok.all() and ledger.verify(signed["db"]) == (True, None)
    idx = int(sigs[sigs.event_type == "decision_mandate"].idx.iloc[0])
    assert idx == out["ledger_idx"] - 1
    ledger.tamper(idx, signed["db"])
    sigs = M.verify_signatures(signed["db"])
    assert ledger.verify(signed["db"]) == (False, idx)
    assert sigs[~sigs.signature_ok].idx.tolist() == [idx]
