import json

import pandas as pd
import pytest

from core import brief, harness, ledger
from core import queue as Q
from core import schema as S

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture(scope="module")
def ctx():
    pol = harness.load_policy()
    q = Q.rank(harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol), pol)
    t = (S.load("claims")[["claim_id", "provider_id", "service_date", "paid_amt"]], S.load("providers"),
         S.load("graph_features"), json.loads(S.RUN_META.read_text()))
    return q, pol, t


def _case(q, pick):
    return q[pick(q)].iloc[0].to_dict()


PICKS = {"ring": lambda q: q.case_type == "ring", "nmd": lambda q: q.recommended_action == "NEEDS_MORE_DATA",
         "provider": lambda q: q.case_type != "ring"}


@pytest.mark.parametrize("kind", PICKS)
def test_all_12_sections_and_deterministic(ctx, kind):
    q, pol, t = ctx
    case = _case(q, PICKS[kind])
    md = brief.build(case, pol, *t, generated_at="2026-01-01 00:00 UTC", ledger_idx=7)
    for i in range(1, 15):
        assert f"\n## {i}. " in md, i
    assert brief.FOOTER in md and case["case_id"] in md and "#7" in md
    assert md == brief.build(case, pol, *t, generated_at="2026-01-01 00:00 UTC", ledger_idx=7)


def test_nmd_brief_lists_requests_for_missing_classes(ctx):
    q, pol, t = ctx
    case = _case(q, PICKS["nmd"])
    md = brief.build(case, pol, *t, generated_at="x", ledger_idx=0)
    assert "- [ ] Member verification calls" in md
    for c in case["missing_classes"]:
        assert brief.REQUESTS[c] in md


def test_generate_appends_brief_block_with_sha(ctx, tmp_path):
    q, pol, t = ctx
    db = tmp_path / "l.db"
    ledger.append("system:test", "probe", {}, db)
    out = brief.generate(_case(q, PICKS["ring"]), pol, *t, db=db, now="2026-01-01 00:00 UTC")
    lg = ledger.read(db)
    assert out["ledger_idx"] == 1 and lg.event_type.iloc[-1] == "brief_generated"
    assert json.loads(lg.payload_json.iloc[-1])["brief_sha256"] == out["sha256"]
    assert "#1 (brief_generated)" in out["markdown"] and ledger.verify(db) == (True, None)
