"""Every policy threshold tested just at and just below its boundary (values read from harness_v1.yaml)."""
import pandas as pd
import pytest

from core import harness
from core import mandate as M
from core import schema as S

POL = harness.load_policy()
A, AB, PR = POL["actions"], POL["abstain"], POL["predictive"]
EPS = 1e-3


def case(classes=("deterministic",), conf=0.9, fused=None, completeness=1.0, usd=10_000.0, sev=4, codes=("R05",),
         **scores) -> dict:
    s = {f"score_{c}": 0.0 for c in harness.EVIDENCE_CLASSES + ["predictive"]}
    s.update({f"score_{c}": conf for c in classes})
    s.update(scores)
    return {"case_id": "X", "classes": list(classes), "codes": list(codes), "confidence": conf,
            "fused_score": conf if fused is None else fused, "completeness": completeness,
            "dollars_at_risk": usd, "max_severity": sev, "providers": ["X"], "flagged_claim_ids": [], "alert_ids": [],
            "evidence": [], **s}


def ev(c: dict) -> dict:
    return harness.evaluate(c, POL)


TWO = ("deterministic", "structural")
MFCU, FULL = A["REFER_TO_MFCU"], A["FULL_INVESTIGATION"]
EM = A["PREPAY_REVIEW"]["any_of"][1]
EDU = A["PROVIDER_EDUCATION"]
STAT_EM = dict(classes=("statistical",), codes=("AN:em_hi_share",), usd=6_000.0, sev=3)
STAT_LIFT = dict(classes=("statistical",), codes=("AN:new_member_ratio",), conf=0.5, fused=0.5)
# (name, at-threshold case, just-below case, action that must be allowed at the threshold only)
BOUNDARIES = [
    ("mfcu min_conf", case(TWO, conf=MFCU["min_conf"], usd=1e5, sev=5), case(TWO, conf=MFCU["min_conf"] - EPS, usd=1e5, sev=5),
     "REFER_TO_MFCU"),
    ("mfcu min_dollars", case(TWO, conf=0.95, usd=MFCU["min_dollars"], sev=5),
     case(TWO, conf=0.95, usd=MFCU["min_dollars"] - 0.01, sev=5), "REFER_TO_MFCU"),
    ("mfcu min_severity", case(TWO, conf=0.95, usd=1e5, sev=MFCU["min_severity"]),
     case(TWO, conf=0.95, usd=1e5, sev=MFCU["min_severity"] - 1), "REFER_TO_MFCU"),
    ("full min_conf", case(conf=FULL["min_conf"], sev=5), case(conf=FULL["min_conf"] - EPS, sev=5), "FULL_INVESTIGATION"),
    ("full det branch $", case(conf=0.8, usd=5_000.0, sev=4), case(conf=0.8, usd=4_999.99, sev=4), "FULL_INVESTIGATION"),
    ("full structural branch severity", case(("structural",), conf=0.8, sev=4), case(("structural",), conf=0.8, sev=3),
     "FULL_INVESTIGATION"),
    ("prepay det min_conf", case(conf=0.55, usd=6_000.0, sev=3), case(conf=0.55 - EPS, usd=6_000.0, sev=3), "PREPAY_REVIEW"),
    ("prepay E/M statistical floor", case(**STAT_EM, conf=0.65, score_statistical=EM["min_class_score"]["statistical"]),
     case(**STAT_EM, conf=0.65, score_statistical=EM["min_class_score"]["statistical"] - EPS), "PREPAY_REVIEW"),
    ("prepay E/M min_conf", case(**STAT_EM, conf=EM["min_conf"], fused=0.65, score_statistical=0.9),
     case(**STAT_EM, conf=EM["min_conf"] - EPS, fused=0.65, score_statistical=0.9), "PREPAY_REVIEW"),
    ("education max_dollars", case(conf=0.5, usd=EDU["max_dollars"], sev=3, codes=("R01",)),
     case(conf=0.5, usd=EDU["max_dollars"] + 0.01, sev=3, codes=("R01",)), "PROVIDER_EDUCATION"),
    ("education max_severity", case(conf=0.5, usd=1_000.0, sev=EDU["max_severity"], codes=("R01",)),
     case(conf=0.5, usd=1_000.0, sev=EDU["max_severity"] + 1, codes=("R01",)), "PROVIDER_EDUCATION"),
    ("abstain statistical_min", case(**STAT_EM, conf=0.65, fused=AB["statistical_min"], score_statistical=0.9),
     case(**STAT_EM, conf=0.65, fused=AB["statistical_min"] - EPS, score_statistical=0.9), "PREPAY_REVIEW"),
    ("abstain min_completeness", case(sev=5, completeness=AB["min_completeness"]),
     case(sev=5, completeness=AB["min_completeness"] - EPS), "FULL_INVESTIGATION"),
    ("predictive lift_min", case(**STAT_LIFT, score_statistical=0.8, score_predictive=PR["lift_min"]),
     case(**STAT_LIFT, score_statistical=0.8, score_predictive=PR["lift_min"] - EPS), "PREPAY_REVIEW"),
    ("predictive statistical floor", case(**STAT_LIFT, score_statistical=PR["statistical_min"], score_predictive=0.9),
     case(**STAT_LIFT, score_statistical=PR["statistical_min"] - EPS, score_predictive=0.9), "PREPAY_REVIEW"),
]


@pytest.mark.parametrize("name, at, below, action", BOUNDARIES, ids=[b[0] for b in BOUNDARIES])
def test_threshold_boundary(name, at, below, action):
    assert action in ev(at)["allowed_actions"], ev(at)["rule_trace"]
    assert action not in ev(below)["allowed_actions"], ev(below)["rule_trace"]


def test_below_abstain_only_safe_actions_and_trace():
    out = ev(case(**STAT_EM, conf=0.65, fused=AB["statistical_min"] - EPS, score_statistical=0.9))
    assert out["recommended_action"] == "NEEDS_MORE_DATA" and out["allowed_actions"] == harness.SAFE
    assert any(t.startswith("abstain:") for t in out["rule_trace"])


@pytest.mark.parametrize("cls", harness.EVIDENCE_CLASSES)
def test_mfcu_never_allowed_with_one_class(cls):
    out = ev(case((cls,), conf=0.99, fused=0.99, usd=1e7, sev=5, codes=("AN:em_hi_share",), score_predictive=1.0))
    assert "REFER_TO_MFCU" not in out["allowed_actions"] and not out["requires_human"]


def test_predictive_never_counts_as_a_class_for_full():
    out = ev(case(("statistical",), conf=0.99, fused=0.99, usd=1e7, sev=5, codes=("AN:pmpm",), score_predictive=1.0))
    assert "FULL_INVESTIGATION" not in out["allowed_actions"] and "REFER_TO_MFCU" not in out["allowed_actions"]
    assert any("evidence classes 1 >= 2" in t for t in out["rule_trace"])


def test_pipeline_cases_never_list_predictive_as_a_class():
    cases = pd.read_parquet(S.CASES)
    assert not any("predictive" in list(c) for c in cases.classes)
    assert (cases.n_classes == cases.classes.map(len)).all()


def test_recommended_is_highest_allowed_and_safe_actions_always_allowed():
    for c in [case(TWO, conf=0.95, usd=1e5, sev=5), case(conf=0.5, usd=1_000.0, sev=3, codes=("R01",)),
              case(**STAT_LIFT, score_statistical=0.1, score_predictive=0.1)]:
        out = ev(c)
        assert set(harness.SAFE) <= set(out["allowed_actions"])
        assert out["recommended_action"] == out["allowed_actions"][0] or out["recommended_action"] in harness.SAFE


def test_decide_rejects_other_without_note_and_unknown_case(signed):
    db = signed["db"]
    cases = harness.evaluate_all(pd.DataFrame([{**case(sev=5), "n_providers": 1, "member_harm_w": 1.0,
                                               "limitations": []}]), POL)
    with pytest.raises(ValueError, match="note is required"):
        harness.decide("X", "FULL_INVESTIGATION", "inv.a", "OTHER", "", cases=cases, policy=POL, db=db)
    with pytest.raises(ValueError, match="unknown case"):
        harness.decide("NOPE", "MONITOR", "inv.a", "EVIDENCE_CORROBORATED", cases=cases, policy=POL, db=db)
    m = M.sign_decision(cases.iloc[0], POL, "NEEDS_MORE_DATA", "INSUFFICIENT_EVIDENCE", "", "inv.a")
    out = harness.decide("X", "NEEDS_MORE_DATA", "inv.a", "INSUFFICIENT_EVIDENCE", cases=cases, policy=POL, db=db,
                         mandate=m)
    assert out["status"] == "EXECUTED" and out["ledger_idx"] == 2
