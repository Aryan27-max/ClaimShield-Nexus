"""PHI minimum-necessary controls (45 CFR 164.502(b)): member ids as stable keyed tokens, DOB as age band, ZIP as
3 digits. Revealing needs a reason and writes a `phi_access` ledger block; auditors may view but never reveal.
Opening a case writes `case_viewed` (audit controls, 45 CFR 164.312(b))."""
import hashlib
import hmac
import re
import secrets

import pandas as pd

from core import identity, ledger
from core import schema as S

MEMBER_RE = re.compile(r"\bM\d{5}\b")
BANDS = [(0, 17, "0-17"), (18, 34, "18-34"), (35, 49, "35-49"), (50, 64, "50-64"), (65, 200, "65+")]
REVEALERS = {"investigator", "siu_lead"}
FIELDS = ["member_id", "dob", "zip"]


def _key() -> bytes:
    path = identity.keys_dir() / "phi_token.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
        path.chmod(0o600)
    return path.read_bytes()


def token(member_id: str) -> str:
    """Stable keyed token (HMAC-SHA256): the same member always maps to the same token, which cannot be reversed."""
    return "MBR-" + hmac.new(_key(), str(member_id).encode(), hashlib.sha256).hexdigest()[:8]


def mask_text(text) -> str:
    return MEMBER_RE.sub(lambda m: token(m.group()), str(text))


def age_band(dob, asof=S.END) -> str:
    if pd.isna(dob):
        return "unknown"
    age = int((pd.Timestamp(asof) - pd.Timestamp(dob)).days // 365.25)
    return next(label for lo, hi, label in BANDS if lo <= age <= hi)


def zip3(z) -> str:
    return f"{str(z)[:3]}**" if pd.notna(z) else "unknown"


def members_view(member_ids, members: pd.DataFrame, reveal: bool = False) -> pd.DataFrame:
    """Members on a case: masked by default; identifiers only when an authorised user has revealed them."""
    m = members[members.member_id.astype(str).isin([str(x) for x in member_ids])]
    out = pd.DataFrame({"member": m.member_id.astype(str).map(token).values, "age_band": m.dob.map(age_band).values,
                        "zip3": m.zip.map(zip3).values, "plan": m.plan.astype(str).values,
                        "deceased": m.dod.notna().values})
    if reveal:
        out = out.assign(member_id=m.member_id.astype(str).values, dob=m.dob.dt.date.values, zip=m.zip.astype(str).values)
    return out.sort_values("member").reset_index(drop=True)


def reveal(user: str, case_id: str, reason: str, fields=FIELDS, db=None) -> dict:
    """Authorises showing identifiers for one case: investigator or lead, with a reason; ledgered as phi_access."""
    role = identity.role(user)
    if role not in REVEALERS:
        raise ValueError(f"{user} ({role}) can view masked data but cannot reveal member details")
    if not str(reason or "").strip():
        raise ValueError("a reason is required to reveal member details")
    return ledger.append(f"human:{user}", "phi_access", {"user": user, "role": role, "case_id": case_id,
                                                          "fields": list(fields), "reason": reason}, db)


def log_case_view(user: str, case_id: str, db=None) -> dict:
    """Audit trail of who opened which case (call once per case per session)."""
    return ledger.append(f"human:{user}", "case_viewed", {"user": user, "role": identity.role(user),
                                                           "case_id": case_id}, db)
