import pandas as pd
import pytest

from core import harness, ledger
from core import queue as Q

POLICY = harness.load_policy()


def _case(case_id="P9999", classes=("deterministic",), conf=0.9, usd=10_000.0, sev=4, codes=("R05",), **kw) -> dict:
    scores = {f"score_{c}": 0.0 for c in harness.EVIDENCE_CLASSES + ["predictive"]}
    scores.update({f"score_{c}": conf for c in classes})
    return {"case_id": case_id, "classes": list(classes), "codes": list(codes), "confidence": conf,
            "fused_score": conf, "completeness": 1.0, "dollars_at_risk": usd, "max_severity": sev,
            "n_providers": 1, "member_harm_w": 1.0, "limitations": [], **scores, **kw}


def _cases(*rows) -> pd.DataFrame:
    return harness.evaluate_all(pd.DataFrame(list(rows)), POLICY)


def test_policy_hash_is_sha256_of_yaml():
    assert len(POLICY["_hash"]) == 64 and POLICY["version"] == 1


def test_weak_statistical_only_abstains():
    ev = harness.evaluate(_case(classes=("statistical",), conf=0.4, codes=("AN:new_member_ratio",)), POLICY)
    assert ev["recommended_action"] == "NEEDS_MORE_DATA"
    assert ev["allowed_actions"] == harness.SAFE
    assert "deterministic" in ev["missing_classes"]


def test_low_completeness_abstains():
    ev = harness.evaluate(_case(completeness=0.5), POLICY)
    assert ev["recommended_action"] == "NEEDS_MORE_DATA"


def test_strong_single_deterministic_reaches_full_investigation():
    ev = harness.evaluate(_case(sev=5), POLICY)
    assert ev["recommended_action"] == "FULL_INVESTIGATION"
    assert any("REFER_TO_MFCU" in t and "fail" in t for t in ev["rule_trace"])


def test_mfcu_needs_two_classes():
    one = harness.evaluate(_case(conf=0.95, usd=90_000, sev=5), POLICY)
    two = harness.evaluate(_case(classes=("deterministic", "structural"), conf=0.95, usd=90_000, sev=5), POLICY)
    assert "REFER_TO_MFCU" not in one["allowed_actions"]
    assert two["recommended_action"] == "REFER_TO_MFCU" and two["requires_human"]


def test_decide_rejects_invalid(tmp_path):
    db = tmp_path / "l.db"
    cases = _cases(_case())
    with pytest.raises(ValueError, match="not allowed"):
        harness.decide("P9999", "REFER_TO_MFCU", "alice", "EVIDENCE_CORROBORATED", cases=cases, db=db)
    with pytest.raises(ValueError, match="reason_code"):
        harness.decide("P9999", "FULL_INVESTIGATION", "alice", "", cases=cases, db=db)
    with pytest.raises(ValueError, match="user_id"):
        harness.decide("P9999", "FULL_INVESTIGATION", " ", "EVIDENCE_CORROBORATED", cases=cases, db=db)
    assert len(ledger.read(db)) == 0 and len(harness.decisions(db)) == 0


def test_decide_writes_decision_and_ledger(tmp_path):
    db = tmp_path / "l.db"
    out = harness.decide("P9999", "FULL_INVESTIGATION", "alice", "EVIDENCE_CORROBORATED", "ok",
                         cases=_cases(_case()), db=db)
    d, lg = harness.decisions(db), ledger.read(db)
    assert len(d) == 1 and len(lg) == 1 and int(d.ledger_idx[0]) == out["ledger_idx"]
    assert lg.event_type[0] == "human_decision" and ledger.verify(db) == (True, None)


def test_queue_respects_capacity():
    rows = [_case(f"P{i:04d}", usd=10_000.0 * (i + 1), sev=4) for i in range(10)]
    rows.append(_case("P0100", classes=("statistical",), conf=0.3, codes=("AN:x",)))
    q = Q.rank(_cases(*rows), POLICY, investigators=1, hours_per_week=50)
    used = q.est_hours[q.status == "in_capacity"].sum()
    assert used <= 50 and (q.status == "deferred").sum() >= 1
    assert q.set_index("case_id").status["P0100"] == "not_queued"
    assert len(q) == 11


def test_must_take_fills_first_and_flags_over_capacity():
    small = [_case(f"P{i:04d}", conf=0.7, usd=1_000_000.0, sev=3, codes=("R01",)) for i in range(5)]
    mfcu = [_case(f"M{i:04d}", classes=("deterministic", "structural"), conf=0.95, usd=30_000.0, sev=4)
            for i in range(3)]
    q = Q.rank(_cases(*small, *mfcu), POLICY, investigators=1, hours_per_week=25).set_index("case_id")
    assert q.loc[["M0000", "M0001", "M0002"], "recommended_action"].eq("REFER_TO_MFCU").all()
    assert q.must_take.sum() == 3
    assert (q.status[q.must_take] == "in_capacity").sum() == 2 and (q.status == "over_capacity").sum() == 1
    assert "deferred" not in set(q.status[q.must_take])
    assert q.attrs["weeks_to_clear"] == round(q.est_hours[q.queued].sum() / 25, 1)


def test_predictive_lift_only_for_strong_statistical_only():
    stat = dict(classes=("statistical",), conf=0.5, codes=("AN:new_member_ratio",))
    lifted = harness.evaluate(_case(**stat, score_statistical=0.8, score_predictive=0.9), POLICY)
    weak = harness.evaluate(_case(**stat, score_statistical=0.6, score_predictive=0.9), POLICY)
    assert lifted["recommended_action"] == "PREPAY_REVIEW" and lifted["predictive_driven"]
    assert weak["recommended_action"] == "NEEDS_MORE_DATA"
    assert harness.PREDICTIVE_NOTE in _cases(_case(**stat, score_statistical=0.8, score_predictive=0.9)).limitations[0]


def test_predictive_never_counts_toward_mfcu():
    ev = harness.evaluate(_case(conf=0.95, usd=90_000, sev=5, score_predictive=1.0), POLICY)
    assert "REFER_TO_MFCU" not in ev["allowed_actions"]
