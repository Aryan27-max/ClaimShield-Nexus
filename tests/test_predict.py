import pandas as pd
import pytest

from core import predict as P
from core import rules, snapshots
from core import schema as S

T0 = pd.Timestamp("2024-09-30")
pytestmark = pytest.mark.skipif(not (S.OUT / "claims.parquet").exists(), reason="run python -m data.gen.synth first")


@pytest.fixture(scope="module")
def full_and_truncated():
    """Feature rows built from all data vs from data truncated at T0: rows with T <= T0 must be identical,
    which proves no feature at T reads anything after T (claims, referrals, investigations, rule flags, graph)."""
    t = {n: S.load(n) for n in ["claims", "members", "providers", "addresses", "referrals", "investigations"]}
    tt = dict(t, claims=t["claims"][t["claims"].service_date <= T0],
              referrals=t["referrals"][t["referrals"].date <= T0],
              investigations=t["investigations"][t["investigations"].closed <= T0])
    out = []
    for d in (t, tt):
        ra = rules.run_rules(d["claims"], d["members"], d["providers"], d["addresses"])
        f = snapshots.build(d, ra)
        out.append(f[f["T"] <= T0].sort_values(["T", "provider_id"]).reset_index(drop=True))
    return out


def test_no_feature_uses_data_after_T(full_and_truncated):
    full, trunc = full_and_truncated
    assert len(full) == len(trunc) > 0
    cols = [c for c in P.FEATURES if c not in ("type", "specialty")]
    pd.testing.assert_frame_equal(full[["T", "provider_id"] + cols], trunc[["T", "provider_id"] + cols],
                                  check_dtype=False, atol=1e-9)


def test_labels_only_where_horizon_fits():
    snap = pd.read_parquet(S.OUT / "snapshots.parquet") if (S.OUT / "snapshots.parquet").exists() else None
    if snap is None:
        pytest.skip("run python -m core.pipeline first")
    for h in snapshots.HORIZONS:
        late = snap["T"] + pd.Timedelta(days=h) > S.END
        assert snap.loc[late, f"label_{h}"].isna().all() and snap.loc[~late, f"label_{h}"].notna().all()
    assert not any(c.startswith(("label_", "bl_")) for c in P.FEATURES)


def test_core_never_reads_ground_truth():
    for p in (S.ROOT / "core").glob("*.py"):
        text = p.read_text()
        assert "ground_truth" not in text and "legit_outliers" not in text, p.name


def test_time_split_has_no_overlap():
    snap = pd.read_parquet(S.OUT / "snapshots.parquet")
    sp = P.split(snap, 90)
    assert sp["fit"]["T"].max() < sp["cal"]["T"].min() <= sp["cal"]["T"].max() < sp["test"]["T"].min()


def test_embargo_train_labels_end_before_next_split():
    snap = pd.read_parquet(S.OUT / "snapshots.parquet")
    for h in snapshots.HORIZONS:
        sp = P.split(snap, h)
        gap = pd.Timedelta(days=h)
        assert len(sp["fit"]) and len(sp["cal"]) and len(sp["test"])
        assert sp["fit"]["T"].max() + gap <= sp["cal"]["T"].min()
        assert sp["cal"]["T"].max() + gap <= sp["test"]["T"].min()


def test_split_needs_enough_history_for_embargo():
    snap = pd.read_parquet(S.OUT / "snapshots.parquet")
    with pytest.raises(ValueError, match="not enough snapshot history"):
        P.split(snap[snap["T"] <= "2024-08-31"], 90)


def test_pipeline_comparison_matches_a_fresh_retrain():
    import json
    from eval.metrics import model_vs_baseline
    meta = json.loads(S.RUN_META.read_text())
    stored = pd.DataFrame(meta["model_comparison"]).set_index(["h", "scorer"]).sort_index()
    fresh = model_vs_baseline().set_index(["h", "scorer"]).sort_index()
    pd.testing.assert_frame_equal(stored, fresh, check_dtype=False)
    base = stored.xs("baseline new-onset", level="scorer")
    assert (base.roc_auc == 0.5).all()
