import pandas as pd
import pytest

from core import ledger, rules
from core import schema as S
from data.gen import synth

EVIDENCE_KEYS = {"claim_id", "field", "value", "expected", "source"}


@pytest.fixture(scope="module")
def data():
    t = synth.generate()
    alerts = rules.run_rules(t["claims"], t["members"], t["providers"], t["addresses"])
    return t, alerts


def test_common_alert_schema(data):
    _, alerts = data
    assert list(alerts.columns) == S.ALERT_COLUMNS
    assert (alerts.lens == "rules").all() and alerts.alert_id.is_unique
    assert alerts.severity.between(1, 5).all() and alerts.score.between(0, 1).all()
    assert (alerts.dollars_at_risk > 0).all()
    for a in alerts.itertuples():
        assert a.evidence and all(set(e) == EVIDENCE_KEYS for e in a.evidence)
        assert {e["claim_id"] for e in a.evidence} <= set(a.claim_ids)
        assert all(e["source"] == f"rules:{a.code}" for e in a.evidence)


@pytest.mark.parametrize("code", ["R01", "R02", "R03", "R04", "R05", "R06"])
def test_rule_fires_on_planted_scheme(data, code):
    t, alerts = data
    gt = t["ground_truth"]
    planted = set(gt.entity_id[gt.scheme == rules.META[code][2]])
    assert planted <= set(alerts.entity_id[alerts.code == code])


def test_r07_flags_billing_excluded_providers(data):
    t, alerts = data
    excluded = set(t["providers"].provider_id[t["providers"].excluded_flag])
    billing = excluded & set(t["claims"].provider_id.astype(str))
    assert billing and set(alerts.entity_id[alerts.code == "R07"]) == billing


def test_no_clean_or_legit_outlier_flagged(data):
    t, alerts = data
    assert set(alerts.entity_id) <= set(t["ground_truth"].entity_id)
    assert not set(alerts.entity_id) & set(t["legit_outliers"].entity_id)


def test_run_summary_logged_to_ledger(data, tmp_path):
    _, alerts = data
    db = tmp_path / "ledger.db"
    rules.log_run(alerts, 0.1, db)
    log = ledger.read(db)
    assert list(log.event_type.unique()) == ["rule_run"] and len(log) == len(rules.META)
    assert ledger.verify(db) == (True, None)
