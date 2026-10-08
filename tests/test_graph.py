import pandas as pd
import pytest

from core import graph, ledger
from core import schema as S

EVIDENCE_KEYS = {"field", "value", "expected", "source"}


@pytest.fixture(scope="module")
def result(tables):
    return graph.run_graph(tables)


def test_common_alert_schema(result):
    alerts, f, _ = result
    assert list(alerts.columns) == S.ALERT_COLUMNS and alerts.alert_id.is_unique
    assert (alerts.lens == "graph").all() and set(alerts.entity_type) == {"provider", "community"}
    assert alerts.score.between(0, 1).all() and alerts.severity.between(1, 5).all()
    for ev in alerts.evidence:
        assert ev and all(set(e) == EVIDENCE_KEYS and e["source"] == "graph" for e in ev)
    assert len(f) == 1200 and f.graph_score.between(0, 1).all()


def test_both_dme_rings_found(tables, result):
    alerts, f, _ = result
    gt = tables["ground_truth"]
    ring = f.set_index("provider_id").ring_id.reindex(gt.entity_id[gt.scheme == "dme_ring"])
    assert ring.notna().all() and ring.nunique() == 2
    rings = alerts[alerts.entity_type == "community"]
    assert set(rings.entity_id) == set(ring) and (rings.severity == 5).all()
    for ev in rings.evidence:
        assert {"owner_id", "address_id", "bank_id", "referral_cycle"} <= {e["field"] for e in ev}


def test_kickback_found_and_no_clean_flagged(tables, result):
    alerts, f, _ = result
    gt = tables["ground_truth"]
    flagged = set(alerts.entity_id[alerts.entity_type == "provider"])
    assert set(gt.entity_id[gt.scheme == "kickback_referral"]) <= flagged
    assert flagged | set(f.provider_id[f.ring_id.notna()]) <= set(gt.entity_id)


def test_legit_outliers_not_top_ranked(tables, result):
    _, f, _ = result
    lo = tables["legit_outliers"]
    assert not set(f.nlargest(20, "graph_score").provider_id) & set(lo.entity_id[lo.kind != "honest_error"])


def test_ego_graph_bounded(result):
    alerts, f, G = result
    ring_id = alerts.entity_id[alerts.entity_type == "community"].iloc[0]
    for ent in [alerts.entity_id.iloc[0], ring_id, "M00001"]:
        sub = graph.ego_graph(ent, G=G, graph_features=f)
        assert 1 < sub.number_of_nodes() <= 150
    assert graph.ego_graph("P0001", max_nodes=10, G=G).number_of_nodes() <= 10


def test_ppr_seeds_only_confirmed_closed_before_snapshot(tables, result):
    _, _, G = result
    inv = tables["investigations"]
    first_close = inv.closed[inv.outcome == "confirmed"].min()
    assert (graph.personalized_pagerank(G, inv, first_close) == 0).all()
    later = graph.personalized_pagerank(G, inv, first_close + pd.Timedelta(days=1))
    assert (later > 0).any()


def test_run_logged_to_ledger(result, tmp_path):
    alerts, f, _ = result
    db = tmp_path / "ledger.db"
    graph.log_run(alerts, f, 0.1, db)
    assert list(ledger.read(db).event_type) == ["lens_run"] and ledger.verify(db) == (True, None)
