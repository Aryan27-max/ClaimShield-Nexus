import shutil

import pandas as pd
import pytest

from core import harness, ledger
from core import policy_edit as PE
from core import schema as S
from eval.metrics import DEMO_THRESHOLDS, validation

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture(scope="module")
def base():
    pol = harness.load_policy()
    return harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol), pol


def test_preview_demo_thresholds(base):
    cases, pol = base
    new = PE.with_thresholds(pol, DEMO_THRESHOLDS)
    d = PE.diff(cases, pol, new)
    assert len(d) > 0 and (d.after == "PREPAY_REVIEW").all() and d.why.str.len().gt(0).all()
    before, after = validation(cases), validation(harness.evaluate_all(cases.drop(columns=harness.OUTPUT_COLS), new))
    assert before["upcoding_prepay_plus"] == 1 and after["upcoding_prepay_plus"] == 5
    assert after["clean_escalated"] == 0 and after["legit_full_or_mfcu"] == 0


def test_preview_does_not_touch_the_policy(base):
    cases, pol = base
    PE.with_thresholds(pol, DEMO_THRESHOLDS)
    assert PE.get_threshold(pol, "abstain.statistical_min") == harness.load_policy()["abstain"]["statistical_min"]


def test_save_writes_new_version_and_ledger_block(base, tmp_path, signed):
    _, pol = base
    folder, db = tmp_path / "policy", tmp_path / "save.db"
    folder.mkdir()
    shutil.copy(S.POLICY, folder / "harness_v1.yaml")
    old_bytes = (folder / "harness_v1.yaml").read_bytes()
    with pytest.raises(ValueError, match="only an SIU lead"):
        PE.save_version(PE.with_thresholds(pol, DEMO_THRESHOLDS), "inv.a", "demo", old=pol, folder=folder, db=db)
    out = PE.save_version(PE.with_thresholds(pol, DEMO_THRESHOLDS), "siu.lead", "demo", old=pol, folder=folder, db=db)
    assert out["path"].endswith("harness_v2.yaml") and (folder / "harness_v1.yaml").read_bytes() == old_bytes
    saved = harness.load_policy(out["path"])
    assert saved["version"] == 2 and saved["parent_hash"] == pol["_hash"] and saved["abstain"]["statistical_min"] == 0.4
    lg = ledger.read(db)
    assert list(lg.event_type) == ["policy_change", "policy_mandate"] and pol["_hash"] in lg.payload_json[0]
    assert out["hash"] in lg.payload_json[0]
    from core import mandate
    assert mandate.policy_status(saved, db)[0] and not mandate.policy_status(pol, db)[0]
    with pytest.raises(ValueError, match="nothing to save"):
        PE.save_version(saved, "siu.lead", "again", old=saved, folder=folder, db=db)
    out3 = PE.save_version(PE.with_thresholds(saved, {"abstain.statistical_min": 0.45}), "siu.lead", "again",
                           old=saved, folder=folder, db=db)
    assert out3["path"].endswith("harness_v3.yaml") and len(ledger.read(db)) == 4
    assert sorted(p.name for p in folder.iterdir()) == ["harness_v1.yaml", "harness_v2.yaml", "harness_v3.yaml"]


def test_save_requires_author_and_reason(base, tmp_path):
    _, pol = base
    with pytest.raises(ValueError):
        PE.save_version(pol, "", "x", old=pol, folder=tmp_path, db=tmp_path / "l.db")


def test_preview_has_no_side_effects(base):
    cases, pol = base
    folder = S.POLICY.parent
    before_files = sorted(p.name for p in folder.iterdir())
    before_v1, n_ledger = S.POLICY.read_bytes(), len(ledger.read())
    new = PE.with_thresholds(pol, DEMO_THRESHOLDS)
    PE.diff(cases, pol, new)
    validation(harness.evaluate_all(cases.drop(columns=harness.OUTPUT_COLS), new))
    assert sorted(p.name for p in folder.iterdir()) == before_files and S.POLICY.read_bytes() == before_v1
    assert len(ledger.read()) == n_ledger


INVALID = [("abstain.statistical_min", 1.5), ("abstain.statistical_min", -0.1), ("predictive.lift_min", 2.0),
           ("actions.REFER_TO_MFCU.min_dollars", -1), ("actions.FULL_INVESTIGATION.min_conf", "high"),
           ("capacity.hours_per_investigator_week", 0), ("capacity.hours_per_investigator_week", -5)]


@pytest.mark.parametrize("path, value", INVALID, ids=[f"{p}={v}" for p, v in INVALID])
def test_invalid_threshold_rejected_with_clear_error(base, path, value):
    _, pol = base
    with pytest.raises(ValueError, match=path.replace(".", r"\.")):
        PE.with_thresholds(pol, {path: value})


@pytest.mark.parametrize("drop", ["capacity", "actions.MONITOR", "est_hours.PREPAY_REVIEW"])
def test_missing_policy_keys_rejected_on_load(tmp_path, drop):
    import yaml
    body = yaml.safe_load(S.POLICY.read_text())
    d, k = PE._walk(body, drop)
    del d[k]
    path = tmp_path / "harness_v9.yaml"
    path.write_text(yaml.safe_dump(body))
    with pytest.raises(ValueError, match="invalid policy"):
        harness.load_policy(path)


def test_hash_changes_iff_content_changes(base, tmp_path):
    _, pol = base
    assert harness.load_policy()["_hash"] == pol["_hash"]
    assert PE.with_thresholds(pol, {}) is pol
    assert PE.with_thresholds(pol, {"abstain.statistical_min": pol["abstain"]["statistical_min"]})["_hash"] == pol["_hash"]
    a, b = PE.with_thresholds(pol, DEMO_THRESHOLDS), PE.with_thresholds(pol, dict(DEMO_THRESHOLDS))
    c = PE.with_thresholds(pol, {**DEMO_THRESHOLDS, "abstain.statistical_min": 0.41})
    assert a["_hash"] == b["_hash"] != pol["_hash"] and c["_hash"] != a["_hash"]
    copy_ = tmp_path / "harness_v1.yaml"
    copy_.write_bytes(S.POLICY.read_bytes())
    assert harness.load_policy(copy_)["_hash"] == pol["_hash"]
    copy_.write_text(S.POLICY.read_text().replace("statistical_min: 0.6", "statistical_min: 0.61", 1))
    assert harness.load_policy(copy_)["_hash"] != pol["_hash"]


def test_save_into_folder_without_versions_continues_numbering(base, tmp_path, signed):
    _, pol = base
    out = PE.save_version(PE.with_thresholds(pol, DEMO_THRESHOLDS), "siu.lead", "demo", old=pol, folder=tmp_path,
                          db=tmp_path / "l2.db")
    assert out["version"] == pol["version"] + 1 and (tmp_path / f"harness_v{out['version']}.yaml").exists()


def test_available_thresholds_skip_paths_missing_from_a_version(base):
    _, pol = base
    trimmed = {k: v for k, v in pol.items() if k != "predictive"}
    avail = PE.available_thresholds(trimmed)
    assert "predictive.lift_min" not in avail and "abstain.statistical_min" in avail
    assert set(PE.available_thresholds(pol)) == set(PE.THRESHOLDS)
