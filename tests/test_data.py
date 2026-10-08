import hashlib

import pandas as pd

from data.gen import synth


def _parquet_sha(df: pd.DataFrame, path) -> str:
    df.to_parquet(path, index=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generator_is_deterministic(tables, tmp_path):
    again = synth.generate()
    assert set(again) == set(tables)
    for name, df in tables.items():
        assert _parquet_sha(df, tmp_path / f"a_{name}.parquet") == _parquet_sha(again[name], tmp_path / f"b_{name}.parquet"), name


def test_generator_respects_hardware_caps(tables):
    from core import schema as S
    assert len(tables["members"]) <= S.N_MEMBERS and len(tables["providers"]) <= S.N_PROVIDERS
    assert len(tables["claims"]) <= S.MAX_CLAIMS
    assert tables["claims"].service_date.between(S.START, S.END).all()
    assert set(tables["ground_truth"].scheme) == set(S.SCHEMES)


def test_missing_data_gives_actionable_error(tmp_path, monkeypatch):
    import pytest

    from core import pipeline
    from core import schema as S
    monkeypatch.setattr(S, "OUT", tmp_path)
    with pytest.raises(FileNotFoundError, match="python -m data.gen.synth"):
        pipeline.run_all()
    with pytest.raises(FileNotFoundError, match="python -m core.pipeline"):
        S.load("graph_features")
