"""Demo identities with Ed25519 signing keys, generated on first use into data/out/keys/ (gitignored).
Private keys never leave that folder. Production would use SSO identities and HSM/KMS-held keys."""
import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from core import schema as S

ALG = "Ed25519"
DEMO = [("siu.lead", "siu_lead"), ("inv.a", "investigator"), ("inv.b", "investigator"), ("auditor", "auditor"),
        ("system", "automation")]
ROLE_LABELS = {"siu_lead": "SIU lead", "investigator": "Investigator", "auditor": "Auditor (read-only)",
               "automation": "Automation (default-deny)"}
KEYS_DIR: Path | None = None  # override (tests); default data/out/keys


def keys_dir() -> Path:
    return Path(KEYS_DIR or S.OUT / "keys")


def fingerprint(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


def ensure() -> dict:
    """Create missing demo keys; returns the public registry {user_id: {user_id, role, public_key, fingerprint}}."""
    d = keys_dir()
    d.mkdir(parents=True, exist_ok=True)
    reg_path = d / "registry.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    changed = False
    for uid, role in DEMO:
        if uid in reg and (d / f"{uid}.pem").exists():
            continue
        key = Ed25519PrivateKey.generate()
        pem = d / f"{uid}.pem"
        pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        pem.chmod(0o600)
        pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        reg[uid] = {"user_id": uid, "role": role, "public_key": base64.b64encode(pub).decode(),
                    "fingerprint": fingerprint(pub)}
        changed = True
    if changed:
        reg_path.write_text(json.dumps(reg, indent=1, sort_keys=True))
    return reg


def registry() -> dict:
    return ensure()


def role(user_id: str) -> str | None:
    entry = registry().get(str(user_id))
    return entry["role"] if entry else None


def people() -> list[str]:
    """Selectable human identities (the automation actor is not a person)."""
    return [u for u, r in DEMO if r != "automation"]


def sign(user_id: str, message: bytes) -> str:
    if user_id not in registry():
        raise ValueError(f"unknown identity {user_id}")
    key = serialization.load_pem_private_key((keys_dir() / f"{user_id}.pem").read_bytes(), password=None)
    return base64.b64encode(key.sign(message)).decode()


def verify(user_id: str, message: bytes, signature: str, expected_fingerprint: str | None = None) -> bool:
    """True only if the registered public key of `user_id` verifies the signature (and matches the fingerprint)."""
    entry = registry().get(str(user_id))
    if not entry or (expected_fingerprint and expected_fingerprint != entry["fingerprint"]):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(entry["public_key"])).verify(
            base64.b64decode(signature or ""), message)
        return True
    except (InvalidSignature, ValueError):
        return False
