import json

import pytest

from core import ledger


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "ledger.db"
    for i in range(5):
        ledger.append("tester", "event", {"i": i}, path)
    return path


def test_chain_links_and_verifies(db):
    df = ledger.read(db)
    assert list(df.idx) == [0, 1, 2, 3, 4]
    assert df.prev_hash.iloc[0] == ledger.GENESIS
    assert (df.prev_hash.iloc[1:].values == df.hash.iloc[:-1].values).all()
    assert json.loads(df.payload_json.iloc[3]) == {"i": 3}
    assert ledger.verify(db) == (True, None)


def test_verify_detects_tamper(db):
    ledger.tamper(2, db)
    assert ledger.verify(db) == (False, 2)


def test_verify_detects_deleted_block(db):
    con = ledger._connect(db)
    with con:
        con.execute("DELETE FROM ledger WHERE idx=1")
    assert ledger.verify(db) == (False, 2)


def test_verify_detects_edited_metadata(db):
    con = ledger._connect(db)
    with con:
        con.execute("UPDATE ledger SET actor='mallory' WHERE idx=4")
    assert ledger.verify(db) == (False, 4)


def test_tamper_missing_idx_raises(db):
    with pytest.raises(IndexError):
        ledger.tamper(99, db)


def test_reset_starts_fresh_chain(db):
    ledger.reset(db)
    assert ledger.read(db).empty
    ledger.append("tester", "event", {"i": 0}, db)
    assert ledger.read(db).prev_hash.iloc[0] == ledger.GENESIS and ledger.verify(db) == (True, None)


EVENTS = ["lens_run", "model_run", "fusion_run", "policy_change", "brief_generated", "human_decision"]


@pytest.mark.parametrize("idx", range(len(EVENTS)), ids=EVENTS)
def test_tamper_on_each_event_type_detected_at_exact_block(tmp_path, idx):
    path = tmp_path / "events.db"
    for i, e in enumerate(EVENTS):
        ledger.append("system:test" if i < 3 else "human:alice", e, {"i": i, "event": e}, path)
    assert ledger.verify(path) == (True, None)
    ledger.tamper(idx, path)
    assert ledger.verify(path) == (False, idx)
    assert json.loads(ledger.read(path).payload_json[idx])["_tampered"] is True


def test_verify_on_empty_ledger(tmp_path):
    path = tmp_path / "empty.db"
    assert ledger.read(path).empty and ledger.verify(path) == (True, None)


def test_concurrent_appends_never_collide(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / "concurrent.db"
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: ledger.append("system:test", "event", {"i": i}, path), range(80)))
    df = ledger.read(path)
    assert list(df.idx) == list(range(80)) and ledger.verify(path) == (True, None)


def test_callable_payload_receives_its_block_index(tmp_path):
    path = tmp_path / "callable.db"
    ledger.append("system:test", "event", {}, path)
    out = ledger.append("system:test", "event", lambda idx: {"cites_block": idx}, path)
    assert out["idx"] == 1 and json.loads(ledger.read(path).payload_json[1]) == {"cites_block": 1}
