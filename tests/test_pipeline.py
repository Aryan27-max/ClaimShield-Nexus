import json
import shutil
import time

import pandas as pd
import pytest

from core import ledger, pipeline, predict
from core import schema as S

INPUTS = ["claims", "members", "providers", "addresses", "referrals", "investigations"]
REAL = {"cases": S.CASES, "meta": S.RUN_META, "ledger": S.LEDGER_DB}
pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """One pipeline run against a temporary copy of the inputs: data/out, models/ and the demo ledger stay untouched."""
    tmp = tmp_path_factory.mktemp("pipeline")
    out = tmp / "out"
    out.mkdir()
    for n in INPUTS:
        shutil.copy(S.OUT / f"{n}.parquet", out / f"{n}.parquet")
    before = {k: (p.stat().st_mtime if p.exists() else None) for k, p in REAL.items()}
    mp = pytest.MonkeyPatch()
    for obj, attr, val in [(S, "OUT", out), (S, "CASES", out / "cases.parquet"), (S, "RUN_META", out / "run_meta.json"),
                           (ledger, "LEDGER_DB", tmp / "l.db"), (predict, "MODELS", tmp / "models")]:
        mp.setattr(obj, attr, val)
    t0 = time.time()
    meta = pipeline.run_all()
    elapsed = time.time() - t0
    cases = pd.read_parquet(S.CASES)
    lg = ledger.read(tmp / "l.db")
    mp.undo()
    return {"meta": meta, "elapsed": elapsed, "cases": cases, "ledger": lg, "db": tmp / "l.db", "before": before}


def test_run_all_under_60s_and_logs_to_ledger(sandbox):
    assert sandbox["elapsed"] < 60
    cases = sandbox["cases"]
    assert len(cases) == sandbox["meta"]["n_cases"] and cases.case_id.is_unique
    assert list(sandbox["ledger"].event_type) == ["lens_run"] * 3 + ["model_run", "fusion_run"]
    assert ledger.verify(sandbox["db"]) == (True, None)


def test_pipeline_test_leaves_real_outputs_untouched(sandbox):
    after = {k: (p.stat().st_mtime if p.exists() else None) for k, p in REAL.items()}
    assert after == sandbox["before"]


def test_pipeline_is_idempotent(sandbox):
    """Same inputs => same cases and the same Merkle root as the run that produced data/out."""
    real_meta = json.loads(S.RUN_META.read_text())
    assert sandbox["meta"]["cases_merkle_root"] == real_meta["cases_merkle_root"]
    assert sandbox["meta"]["funnel"] == real_meta["funnel"] and sandbox["meta"]["actions"] == real_meta["actions"]
    real = pd.read_parquet(S.CASES)
    cols = ["case_id", "recommended_action", "confidence", "dollars_at_risk", "n_flagged_claims", "est_hours"]
    pd.testing.assert_frame_equal(sandbox["cases"][cols], real[cols])
    pd.testing.assert_frame_equal(sandbox["cases"][["p_30", "p_60", "p_90"]], real[["p_30", "p_60", "p_90"]], atol=1e-3)


def test_merkle_root_changes_with_any_leaf():
    a = pipeline.merkle_root(["a", "b", "c"])
    assert a != pipeline.merkle_root(["a", "b", "d"]) and len(a) == 64
