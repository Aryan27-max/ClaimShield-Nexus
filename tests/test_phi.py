import json

import pandas as pd
import pytest

from core import brief, harness, ledger, phi
from core import queue as Q
from core import schema as S

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


def test_tokens_are_stable_keyed_and_unlinkable(signed):
    t = phi.token("M00042")
    assert t == phi.token("M00042") and t.startswith("MBR-") and "00042" not in t and t != phi.token("M00043")
    assert phi.mask_text("dup of M00042 99214 x1") == f"dup of {t} 99214 x1"
    assert phi.age_band(pd.Timestamp("2010-01-01")) == "0-17" and phi.age_band(pd.Timestamp("1950-01-01")) == "65+"
    assert phi.zip3("75001") == "750**"


def test_members_view_masked_unless_revealed(signed):
    members = S.load("members")
    ids = members.member_id.astype(str).head(3).tolist()
    masked = phi.members_view(ids, members)
    assert "member_id" not in masked and "dob" not in masked and masked.zip3.str.endswith("**").all()
    assert {"member_id", "dob", "zip"} <= set(phi.members_view(ids, members, reveal=True).columns)


def test_brief_masks_member_ids(signed):
    pol = harness.load_policy()
    q = Q.rank(harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol), pol)
    dup = q[q.codes.map(lambda c: "R01" in list(c))].iloc[0].to_dict()
    raw = [e["value"] for e in dup["evidence"] if phi.MEMBER_RE.search(e["value"])]
    assert raw
    md = brief.build(dup, pol, S.load("claims")[["claim_id", "provider_id", "service_date", "paid_amt"]],
                     S.load("providers"), S.load("graph_features"), json.loads(S.RUN_META.read_text()), "x", 0)
    assert not phi.MEMBER_RE.search(md) and "MBR-" in md and "## 11. Regulatory basis" in md


def test_reveal_needs_reason_and_role_and_is_ledgered(signed):
    db = signed["db"]
    with pytest.raises(ValueError, match="cannot reveal"):
        phi.reveal("auditor", "P0001", "audit sample", db=db)
    with pytest.raises(ValueError, match="reason"):
        phi.reveal("inv.a", "P0001", " ", db=db)
    phi.reveal("inv.a", "P0001", "verify member services", db=db)
    last = ledger.read(db).iloc[-1]
    body = json.loads(last.payload_json)
    assert last.event_type == "phi_access" and body["fields"] == phi.FIELDS and body["reason"] == "verify member services"
