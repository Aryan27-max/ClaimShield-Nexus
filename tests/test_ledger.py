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
