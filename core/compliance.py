"""Compliance obligations, created ONLY from executed human decisions (never from model scores).
REFER_TO_MFCU => payment-suspension determination, written MFCU referral (next business day), MFCU certification
every 90 days while open. OVERPAYMENT_IDENTIFIED => 60-day report-and-return clock (180-day good-faith pause only for
programs the policy allows). All date math takes an injectable `asof`. Not legal advice; state rules vary."""
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from core import identity, ledger

DDL = """CREATE TABLE IF NOT EXISTS obligations (obligation_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
    decision_id INTEGER, type TEXT NOT NULL, due_date TEXT NOT NULL, status TEXT NOT NULL, basis TEXT NOT NULL,
    created_from TEXT NOT NULL, created_at TEXT NOT NULL, amount REAL, determination TEXT, good_cause TEXT,
    met_by TEXT, met_at TEXT, note TEXT, paused_days INTEGER DEFAULT 0)"""
TYPES = {"SUSPENSION_DETERMINATION": "Payment-suspension determination (suspend or good cause)",
         "MFCU_REFERRAL": "Written MFCU referral", "MFCU_CERTIFICATION": "MFCU certification (every 90 days while open)",
         "OVERPAYMENT_RETURN": "Report and return the overpayment"}
GOOD_CAUSE = {"law_enforcement_request": "Law-enforcement request", "member_access_to_care": "Member access to care",
              "other_documented": "Other documented good cause"}
CERT_DAYS, RETURN_DAYS, MAX_PAUSE_DAYS = 90, 60, 180
DOERS = {"investigator", "siu_lead"}


def _db(db) -> sqlite3.Connection:
    con = sqlite3.connect(Path(db or ledger.LEDGER_DB))
    con.execute(DDL)
    return con


def _day(asof) -> date:
    return pd.Timestamp(asof).date() if asof is not None else date.today()


def next_business_day(d: date) -> date:
    """The next weekday after d (federal holidays are out of scope)."""
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _insert(rows: list[dict], db) -> list[int]:
    ids = []
    with closing(_db(db)) as con, con:
        for r in rows:
            cur = con.execute("INSERT INTO obligations (case_id, decision_id, type, due_date, status, basis, created_from, "
                              "created_at, amount) VALUES (?,?,?,?,?,?,?,?,?)",
                              (r["case_id"], r.get("decision_id"), r["type"], r["due_date"], "OPEN", r["basis"],
                               r["created_from"], r["created_at"], r.get("amount")))
            ids.append(cur.lastrowid)
    for i, r in zip(ids, rows):
        ledger.append("system:compliance", "compliance_event", {"event": "obligation_created", "obligation_id": i, **r},
                      db)
    return ids


def on_executed(decision: dict, policy: dict, created_from: str, asof=None, db=None) -> list[int]:
    """Obligations for an EXECUTED decision; returns their ids (none for actions without obligations)."""
    day, rb = _day(asof), policy.get("regulatory_basis", {})
    base = {"case_id": decision["case_id"], "decision_id": int(decision["decision_id"]), "created_from": created_from,
            "created_at": day.isoformat()}
    rows = []
    if decision["action"] == "REFER_TO_MFCU":
        cite = rb.get("actions", {}).get("REFER_TO_MFCU", "42 CFR 455.23")
        nbd = next_business_day(day).isoformat()
        rows += [{**base, "type": "SUSPENSION_DETERMINATION", "due_date": nbd, "basis": cite},
                 {**base, "type": "MFCU_REFERRAL", "due_date": nbd, "basis": cite},
                 {**base, "type": "MFCU_CERTIFICATION", "due_date": (day + timedelta(days=CERT_DAYS)).isoformat(),
                  "basis": cite}]
    if decision.get("reason_code") == "OVERPAYMENT_IDENTIFIED":
        rows.append({**base, "type": "OVERPAYMENT_RETURN", "amount": float(decision.get("amount") or 0),
                     "due_date": (day + timedelta(days=RETURN_DAYS)).isoformat(),
                     "basis": rb.get("overpayment", "42 U.S.C. 1320a-7k(d)")})
    return _insert(rows, db) if rows else []


def obligations(db=None, asof=None, case_id: str | None = None) -> pd.DataFrame:
    """All obligations with status evaluated at `asof`: an OPEN obligation past its due date is OVERDUE."""
    with closing(_db(db)) as con:
        df = pd.read_sql("SELECT * FROM obligations ORDER BY due_date, obligation_id", con)
    if case_id is not None:
        df = df[df.case_id == case_id]
    late = (df.status == "OPEN") & (pd.to_datetime(df.due_date).dt.date < _day(asof))
    return df.assign(status=df.status.where(~late, "OVERDUE"), label=df.type.map(TYPES))


def _get(obligation_id: int, db) -> dict:
    df = obligations(db)
    row = df[df.obligation_id == int(obligation_id)]
    if row.empty:
        raise ValueError(f"unknown obligation {obligation_id}")
    return row.iloc[0].to_dict()


def _complete(obligation_id: int, user: str, note: str, db, asof, event: str, **fields) -> dict:
    if identity.role(user) not in DOERS:
        raise ValueError(f"{user} ({identity.role(user)}) may not complete obligations")
    if not str(note or "").strip():
        raise ValueError("a note is required")
    ob = _get(obligation_id, db)
    if ob["status"] == "MET":
        raise ValueError(f"obligation {obligation_id} is already met")
    met_at = _day(asof).isoformat()
    cols = {"status": "MET", "met_by": user, "met_at": met_at, "note": note, **fields}
    with closing(_db(db)) as con, con:
        con.execute(f"UPDATE obligations SET {', '.join(f'{k}=?' for k in cols)} WHERE obligation_id=?",
                    (*cols.values(), int(obligation_id)))
    entry = ledger.append(f"human:{user}", "compliance_event", {"event": event, "obligation_id": int(obligation_id),
                                                                "case_id": ob["case_id"], "type": ob["type"], **cols}, db)
    return {"ledger_idx": entry["idx"], **ob, **cols}


def mark_met(obligation_id: int, user: str, note: str, db=None, asof=None) -> dict:
    """Records completion (identity + note, ledgered). A met MFCU certification schedules the next one (+90 days)."""
    ob = _get(obligation_id, db)
    if ob["type"] == "SUSPENSION_DETERMINATION":
        raise ValueError("record the suspension determination with record_suspension()")
    out = _complete(obligation_id, user, note, db, asof, "obligation_met")
    if ob["type"] == "MFCU_CERTIFICATION":
        due = (pd.Timestamp(ob["due_date"]).date() + timedelta(days=CERT_DAYS)).isoformat()
        _insert([{k: ob[k] for k in ("case_id", "decision_id", "basis", "created_from")} |
                 {"type": "MFCU_CERTIFICATION", "due_date": due, "created_at": _day(asof).isoformat()}], db)
    return out


def record_suspension(obligation_id: int, determination: str, user: str, note: str, good_cause: str | None = None,
                      db=None, asof=None) -> dict:
    """SUSPEND, or GOOD_CAUSE with one of GOOD_CAUSE reasons and a documented note (42 CFR 455.23)."""
    if _get(obligation_id, db)["type"] != "SUSPENSION_DETERMINATION":
        raise ValueError("not a suspension determination")
    if determination not in ("SUSPEND", "GOOD_CAUSE"):
        raise ValueError("determination must be SUSPEND or GOOD_CAUSE")
    if determination == "GOOD_CAUSE" and good_cause not in GOOD_CAUSE:
        raise ValueError(f"good cause must be one of {list(GOOD_CAUSE)}")
    return _complete(obligation_id, user, note, db, asof, "suspension_determination", determination=determination,
                     good_cause=good_cause if determination == "GOOD_CAUSE" else None)


def pause_allowed(policy: dict) -> tuple[bool, str]:
    program, allowed = policy.get("program", "medicaid"), policy.get("allow_pause_programs", [])
    if program in allowed:
        return True, f"{program}: up to {MAX_PAUSE_DAYS}-day good-faith investigation before the 60 days run"
    return False, (f"{program}: no good-faith investigation pause; the 60-day clock runs from identification "
                   f"(pause applies only to {', '.join(allowed) or 'no program'})")


def pause(obligation_id: int, days: int, user: str, note: str, policy: dict, db=None) -> dict:
    """Good-faith investigation pause on an overpayment: due = identified + days + 60 (allowed programs only)."""
    ok, why = pause_allowed(policy)
    if not ok:
        raise ValueError(why)
    ob = _get(obligation_id, db)
    if ob["type"] != "OVERPAYMENT_RETURN" or ob["status"] == "MET":
        raise ValueError("only an open overpayment return can be paused")
    if not 1 <= int(days) <= MAX_PAUSE_DAYS or identity.role(user) not in DOERS or not str(note or "").strip():
        raise ValueError(f"pause needs 1-{MAX_PAUSE_DAYS} days, an investigator or lead, and a note")
    due = (pd.Timestamp(ob["created_at"]).date() + timedelta(days=int(days) + RETURN_DAYS)).isoformat()
    with closing(_db(db)) as con, con:
        con.execute("UPDATE obligations SET due_date=?, paused_days=?, note=? WHERE obligation_id=?",
                    (due, int(days), note, int(obligation_id)))
    entry = ledger.append(f"human:{user}", "compliance_event", {"event": "overpayment_pause", "obligation_id":
                                                                int(obligation_id), "days": int(days), "due_date": due,
                                                                "note": note, "basis": policy.get(
                                                                    "regulatory_basis", {}).get("overpayment_pause")}, db)
    return {"ledger_idx": entry["idx"], "due_date": due}


def summary(db=None, asof=None, days: int = 7) -> dict:
    """Overview tiles: open obligations due within `days`, overdue, and decisions pending a second signature."""
    ob, today = obligations(db, asof), _day(asof)
    due = pd.to_datetime(ob.due_date).dt.date
    with closing(_db(db)) as con:
        has = con.execute("SELECT name FROM sqlite_master WHERE name='decisions'").fetchone()
        pending = con.execute("SELECT COUNT(*) FROM decisions WHERE status='PENDING_APPROVAL'").fetchone()[0] if has else 0
    return {"due_soon": int(((ob.status == "OPEN") & (due <= today + timedelta(days=days))).sum()),
            "overdue": int((ob.status == "OVERDUE").sum()), "pending_approval": int(pending),
            "generated_at": datetime.now(timezone.utc).isoformat()}


def next_deadlines(db=None, asof=None) -> pd.Series:
    """case_id -> earliest due date among its unmet obligations (for the queue)."""
    ob = obligations(db, asof)
    return ob[ob.status != "MET"].groupby("case_id").due_date.min()
