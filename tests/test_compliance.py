from datetime import date

import pandas as pd
import pytest

from core import compliance as CO
from core import harness, ledger
from core import mandate as M
from core import schema as S

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")
FRI = "2026-10-09"


@pytest.fixture(scope="module")
def cases():
    pol = harness.load_policy()
    return harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol)


def _run(signed, cases, action, reason="EVIDENCE_CORROBORATED", user="inv.a", amount=None, asof=FRI, policy=None):
    pol = policy or signed["policy"]
    case = cases[cases.recommended_action == action].iloc[0]
    m = M.sign_decision(case, pol, action, reason, "", user, amount)
    return case, harness.decide(case.case_id, action, user, reason, "", cases=cases, policy=pol, db=signed["db"],
                                mandate=m, amount=amount, asof=asof)


@pytest.mark.parametrize("day, expected", [("2026-10-09", "2026-10-12"), ("2026-10-10", "2026-10-12"),
                                           ("2026-10-11", "2026-10-12"), ("2026-10-07", "2026-10-08")])
def test_next_business_day_skips_weekends(day, expected):
    assert CO.next_business_day(date.fromisoformat(day)).isoformat() == expected


def test_obligations_only_from_executed_decisions(signed, cases):
    case, out = _run(signed, cases, "REFER_TO_MFCU")
    assert out["status"] == "PENDING_APPROVAL" and CO.obligations(signed["db"]).empty
    M.approve(out["decision_id"], "siu.lead", signed["policy"], db=signed["db"], asof=FRI)
    ob = CO.obligations(signed["db"], asof=FRI).set_index("type")
    assert set(ob.index) == {"SUSPENSION_DETERMINATION", "MFCU_REFERRAL", "MFCU_CERTIFICATION"}
    assert ob.due_date["MFCU_REFERRAL"] == "2026-10-12" and ob.due_date["MFCU_CERTIFICATION"] == "2027-01-07"
    assert (ob.created_from == M.verify_chain(case.case_id, signed["db"])[0]["block"]["mandate_hash"]).all()
    assert "455.23" in ob.basis["MFCU_REFERRAL"] and (ob.status == "OPEN").all()
    _, edu = _run(signed, cases, "PROVIDER_EDUCATION")
    assert edu["status"] == "EXECUTED" and edu["obligations"] == []


def test_overdue_when_asof_passes_due(signed, cases):
    _, out = _run(signed, cases, "REFER_TO_MFCU")
    M.approve(out["decision_id"], "siu.lead", signed["policy"], db=signed["db"], asof=FRI)
    ob = CO.obligations(signed["db"], asof="2026-10-13")
    assert set(ob.status[ob.type != "MFCU_CERTIFICATION"]) == {"OVERDUE"}
    assert CO.summary(signed["db"], asof="2026-10-13")["overdue"] == 2
    assert CO.summary(signed["db"], asof=FRI)["due_soon"] == 2


def test_certification_every_90_days(signed, cases):
    _, out = _run(signed, cases, "REFER_TO_MFCU")
    M.approve(out["decision_id"], "siu.lead", signed["policy"], db=signed["db"], asof=FRI)
    ob = CO.obligations(signed["db"], asof=FRI)
    cert = int(ob.obligation_id[ob.type == "MFCU_CERTIFICATION"].iloc[0])
    with pytest.raises(ValueError, match="note"):
        CO.mark_met(cert, "inv.a", "", db=signed["db"], asof="2027-01-05")
    with pytest.raises(ValueError, match="may not complete"):
        CO.mark_met(cert, "auditor", "done", db=signed["db"], asof="2027-01-05")
    CO.mark_met(cert, "inv.a", "certified to MFCU", db=signed["db"], asof="2027-01-05")
    certs = CO.obligations(signed["db"], asof="2027-01-05").query("type == 'MFCU_CERTIFICATION'")
    assert certs.status.tolist() == ["MET", "OPEN"] and certs.due_date.tolist() == ["2027-01-07", "2027-04-07"]
    assert ledger.read(signed["db"]).event_type.iloc[-2:].tolist() == ["compliance_event", "compliance_event"]


def test_suspension_determination_rules(signed, cases):
    _, out = _run(signed, cases, "REFER_TO_MFCU")
    M.approve(out["decision_id"], "siu.lead", signed["policy"], db=signed["db"], asof=FRI)
    ob = CO.obligations(signed["db"], asof=FRI)
    sid = int(ob.obligation_id[ob.type == "SUSPENSION_DETERMINATION"].iloc[0])
    with pytest.raises(ValueError, match="good cause"):
        CO.record_suspension(sid, "GOOD_CAUSE", "inv.a", "investigation ongoing", None, db=signed["db"])
    with pytest.raises(ValueError, match="note"):
        CO.record_suspension(sid, "GOOD_CAUSE", "inv.a", "", "law_enforcement_request", db=signed["db"])
    with pytest.raises(ValueError, match="record_suspension"):
        CO.mark_met(sid, "inv.a", "done", db=signed["db"])
    rec = CO.record_suspension(sid, "GOOD_CAUSE", "siu.lead", "MFCU asked us not to suspend",
                               "law_enforcement_request", db=signed["db"], asof=FRI)
    assert rec["status"] == "MET" and rec["determination"] == "GOOD_CAUSE"


def test_sixty_day_overpayment_clock(signed, cases):
    _, out = _run(signed, cases, "PREPAY_REVIEW", reason="OVERPAYMENT_IDENTIFIED", amount=12_500.0)
    ob = CO.obligations(signed["db"], asof=FRI)
    assert out["status"] == "EXECUTED" and ob.type.tolist() == ["OVERPAYMENT_RETURN"]
    assert ob.due_date.iloc[0] == "2026-12-08" and ob.amount.iloc[0] == 12_500.0 and "1320a-7k(d)" in ob.basis.iloc[0]
    with pytest.raises(ValueError, match="amount"):
        _run(signed, cases, "PREPAY_REVIEW", reason="OVERPAYMENT_IDENTIFIED", amount=None)


def test_180_day_pause_only_for_medicare_ab(signed, cases, tmp_path):
    _, out = _run(signed, cases, "PREPAY_REVIEW", reason="OVERPAYMENT_IDENTIFIED", amount=900.0)
    oid = int(CO.obligations(signed["db"]).obligation_id.iloc[0])
    pol = signed["policy"]
    assert pol["program"] == "medicaid" and not CO.pause_allowed(pol)[0]
    with pytest.raises(ValueError, match="no good-faith investigation pause"):
        CO.pause(oid, 90, "inv.a", "auditing claims", pol, db=signed["db"])
    for program, ok in [("medicare_ab", True), ("medicare_advantage", False), ("part_d", False)]:
        assert CO.pause_allowed({**pol, "program": program})[0] is ok
    with pytest.raises(ValueError, match="days"):
        CO.pause(oid, 181, "inv.a", "too long", {**pol, "program": "medicare_ab"}, db=signed["db"])
    res = CO.pause(oid, 120, "inv.a", "good-faith review", {**pol, "program": "medicare_ab"}, db=signed["db"])
    assert res["due_date"] == "2027-04-07"


def test_regulatory_basis_in_rule_trace(cases):
    mfcu = cases[cases.recommended_action == "REFER_TO_MFCU"].iloc[0]
    assert any(t.startswith("regulatory basis (REFER_TO_MFCU): 42 CFR 455.23") for t in mfcu.rule_trace)
    r07 = cases[cases.codes.map(lambda c: "R07" in list(c))]
    assert len(r07) and any("455.436" in t for t in r07.iloc[0].rule_trace)
