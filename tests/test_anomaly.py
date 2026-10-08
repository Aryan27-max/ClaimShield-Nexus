import pandas as pd
import pytest

from core import anomaly, ledger
from core import schema as S

EVIDENCE_KEYS = {"field", "value", "expected", "source"}


@pytest.fixture(scope="module")
def result(tables):
    return anomaly.run_anomaly(tables["claims"], tables["providers"])


def test_common_alert_schema(result):
    alerts, sc = result
    assert list(alerts.columns) == S.ALERT_COLUMNS and alerts.alert_id.is_unique
    assert (alerts.lens == "anomaly").all() and (alerts.entity_type == "provider").all()
    assert alerts.score.between(anomaly.ALERT_MIN, 1).all() and alerts.severity.between(1, 5).all()
    assert (alerts.dollars_at_risk >= 0).all() and alerts.claim_ids.map(len).gt(0).all()
    for ev in alerts.evidence:
        assert 1 <= len(ev) <= anomaly.TOP_DRIVERS and all(set(e) == EVIDENCE_KEYS for e in ev)
        assert all(e["source"] == "anomaly" and e["field"] in anomaly.FEATURES for e in ev)
    assert len(sc) == 1200 and sc.score.between(0, 1).all()


def test_upcoding_flagged(tables, result):
    alerts, _ = result
    gt = tables["ground_truth"]
    up = set(gt.entity_id[gt.scheme == "upcoding"])
    assert len(up & set(alerts.entity_id)) >= 0.7 * len(up)


def test_legit_outliers_not_top_ranked(tables, result):
    _, sc = result
    lo = tables["legit_outliers"]
    top20 = set(sc.nlargest(20, "score").provider_id)
    assert not top20 & set(lo.entity_id[lo.kind != "honest_error"])


def test_no_future_data_used(tables):
    asof = S.END - pd.Timedelta(days=180)
    f = anomaly.features(tables["claims"], tables["providers"], asof)
    late = tables["claims"][tables["claims"].service_date > asof]
    assert f.n_claims_full.sum() == len(tables["claims"]) - len(late)


def test_run_logged_to_ledger(result, tmp_path):
    alerts, sc = result
    db = tmp_path / "ledger.db"
    anomaly.log_run(alerts, sc, 0.1, db)
    log = ledger.read(db)
    assert list(log.event_type) == ["lens_run"] and ledger.verify(db) == (True, None)
