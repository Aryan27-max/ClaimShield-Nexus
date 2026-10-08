import shutil

import pandas as pd
import pytest

from core import harness, ledger
from core import schema as S
from eval.metrics import DEMO_THRESHOLDS, validation

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture(scope="module")
def base():
    pol = harness.load_policy()
    return harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol), pol


def test_preview_demo_thresholds(base):
    cases, pol = base
    new = harness.with_thresholds(pol, DEMO_THRESHOLDS)
    d = harness.diff(cases, pol, new)
    assert len(d) > 0 and (d.after == "PREPAY_REVIEW").all() and d.why.str.len().gt(0).all()
    before, after = validation(cases), validation(harness.evaluate_all(cases.drop(columns=harness.OUTPUT_COLS), new))
    assert before["upcoding_prepay_plus"] == 1 and after["upcoding_prepay_plus"] == 5
    assert after["clean_escalated"] == 0 and after["legit_full_or_mfcu"] == 0


def test_preview_does_not_touch_the_policy(base):
    cases, pol = base
    harness.with_thresholds(pol, DEMO_THRESHOLDS)
    assert harness.get_threshold(pol, "abstain.statistical_min") == harness.load_policy()["abstain"]["statistical_min"]


def test_save_writes_new_version_and_ledger_block(base, tmp_path):
    _, pol = base
    folder, db = tmp_path / "policy", tmp_path / "l.db"
    folder.mkdir()
    shutil.copy(S.POLICY, folder / "harness_v1.yaml")
    old_bytes = (folder / "harness_v1.yaml").read_bytes()
    out = harness.save_version(harness.with_thresholds(pol, DEMO_THRESHOLDS), "lead", "demo", old=pol, folder=folder, db=db)
    assert out["path"].endswith("harness_v2.yaml") and (folder / "harness_v1.yaml").read_bytes() == old_bytes
    saved = harness.load_policy(out["path"])
    assert saved["version"] == 2 and saved["parent_hash"] == pol["_hash"] and saved["abstain"]["statistical_min"] == 0.4
    lg = ledger.read(db)
    assert len(lg) == 1 and lg.event_type[0] == "policy_change" and pol["_hash"] in lg.payload_json[0]
    assert out["hash"] in lg.payload_json[0]
    out3 = harness.save_version(saved, "lead", "again", old=saved, folder=folder, db=db)
    assert out3["path"].endswith("harness_v3.yaml")


def test_save_requires_author_and_reason(base, tmp_path):
    _, pol = base
    with pytest.raises(ValueError):
        harness.save_version(pol, "", "x", old=pol, folder=tmp_path, db=tmp_path / "l.db")
