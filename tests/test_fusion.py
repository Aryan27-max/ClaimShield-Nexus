import json

import pandas as pd
import pytest

from core import brief, fusion, harness
from core import queue as Q
from core import schema as S

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture(scope="module")
def t():
    return {n: S.load(n) for n in ["claims", "members", "providers", "referrals"]}


def test_no_alerts_gives_empty_cases_that_flow_through_harness_and_queue(t):
    pol = harness.load_policy()
    empty = pd.DataFrame(columns=S.ALERT_COLUMNS)
    cases = fusion.build_cases(empty, t, S.load("graph_features"), pol, None)
    assert cases.empty and set(fusion.CASE_COLUMNS) <= set(cases.columns)
    ev = harness.evaluate_all(cases, pol)
    assert ev.empty and set(harness.OUTPUT_COLS) <= set(ev.columns)
    q = Q.rank(ev, pol)
    assert q.empty and q.attrs["weeks_to_clear"] == 0 and q.attrs["used_hours"] == 0
    assert fusion.funnel(empty, cases) == {"claims_flagged": 0, "alerts": 0, "cases": 0}


def test_case_columns_match_built_cases():
    cases = pd.read_parquet(S.CASES)
    assert list(cases.columns[:len(fusion.CASE_COLUMNS)]) == fusion.CASE_COLUMNS


def test_ring_brief_lists_each_community_of_its_members():
    pol = harness.load_policy()
    q = Q.rank(harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol), pol)
    gf = S.load("graph_features")
    ring = q[q.case_type == "ring"].iloc[0].to_dict()
    md = brief.build(ring, pol, S.load("claims"), S.load("providers"), gf, json.loads(S.RUN_META.read_text()), "x", 0)
    members = gf[gf.provider_id.astype(str).isin(ring["providers"])]
    for cid in members.community_id.unique():
        assert f"{cid} (size" in md
    assert f"holds {len(members)} of them" in md or members.community_id.nunique() > 1
