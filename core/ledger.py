"""Append-only SHA-256 hash-chained audit ledger in SQLite."""
import hashlib
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.schema import LEDGER_DB

GENESIS = "0" * 64
DDL = """CREATE TABLE IF NOT EXISTS ledger (
    idx INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL, payload_sha TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL)"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _block_hash(prev_hash: str, payload_sha: str, ts: str, actor: str, event_type: str) -> str:
    return _sha(prev_hash + payload_sha + ts + actor + event_type)


def _connect(db: Path | None) -> sqlite3.Connection:
    """Autocommit connection (explicit transactions only); waits up to 30 s for another writer."""
    db = Path(db or LEDGER_DB)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, timeout=30, isolation_level=None)
    con.execute(DDL)
    return con


def append(actor: str, event_type: str, payload: dict | Callable[[int], dict], db: Path | None = None) -> dict:
    """Append one event; returns its idx and hash. Writers are serialised (BEGIN IMMEDIATE), so concurrent sessions
    never collide or fork the chain. A callable payload is called with the index the block will occupy."""
    with closing(_connect(db)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            last = con.execute("SELECT idx, hash FROM ledger ORDER BY idx DESC LIMIT 1").fetchone()
            idx, prev = (last[0] + 1, last[1]) if last else (0, GENESIS)
            body = json.dumps(payload(idx) if callable(payload) else payload, sort_keys=True, default=str)
            ts = datetime.now(timezone.utc).isoformat()
            psha = _sha(body)
            h = _block_hash(prev, psha, ts, actor, event_type)
            con.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)", (idx, ts, actor, event_type, body, psha, prev, h))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return {"idx": idx, "hash": h}


def read(db: Path | None = None) -> pd.DataFrame:
    with closing(_connect(db)) as con:
        return pd.read_sql("SELECT * FROM ledger ORDER BY idx", con)


def verify(db: Path | None = None) -> tuple[bool, int | None]:
    """Recompute every hash; returns (ok, first broken idx)."""
    prev = GENESIS
    for r in read(db).itertuples():
        psha = _sha(r.payload_json)
        if psha != r.payload_sha or r.prev_hash != prev or \
                _block_hash(prev, psha, r.ts, r.actor, r.event_type) != r.hash:
            return False, int(r.idx)
        prev = r.hash
    return True, None


def reset(db: Path | None = None) -> None:
    """Dev helper: delete the ledger DB and recreate an empty chain."""
    Path(db or LEDGER_DB).unlink(missing_ok=True)
    _connect(db).close()


def tamper(idx: int, db: Path | None = None) -> None:
    """Demo helper: silently edit a block's payload without re-hashing."""
    with closing(_connect(db)) as con:
        body = con.execute("SELECT payload_json FROM ledger WHERE idx=?", (idx,)).fetchone()
        if body is None:
            raise IndexError(idx)
        data = json.loads(body[0])
        data["_tampered"] = True
        con.execute("UPDATE ledger SET payload_json=? WHERE idx=?", (json.dumps(data, sort_keys=True), idx))
