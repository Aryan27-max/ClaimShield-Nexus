import time

import pandas as pd
import pytest

from core import ledger, pipeline
from core import schema as S


@pytest.mark.skipif(not (S.OUT / "claims.parquet").exists(), reason="run python -m data.gen.synth first")
def test_run_all_under_60s(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_DB", tmp_path / "l.db")
    t0 = time.time()
    meta = pipeline.run_all()
    elapsed = time.time() - t0
    print(f"pipeline {elapsed:.1f}s")
    assert elapsed < 60
    cases = pd.read_parquet(S.CASES)
    assert len(cases) == meta["n_cases"] and cases.case_id.is_unique
    lg = ledger.read(tmp_path / "l.db")
    assert list(lg.event_type) == ["lens_run"] * 3 + ["model_run", "fusion_run"]
    assert ledger.verify(tmp_path / "l.db") == (True, None)


def test_merkle_root_changes_with_any_leaf():
    a = pipeline.merkle_root(["a", "b", "c"])
    assert a != pipeline.merkle_root(["a", "b", "d"]) and len(a) == 64
