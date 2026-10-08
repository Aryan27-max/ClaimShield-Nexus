import pytest

from data.gen import synth


@pytest.fixture(scope="session")
def tables():
    return synth.generate()


@pytest.fixture
def signed(tmp_path, monkeypatch):
    """Temporary demo keys and ledger in which the shipped policy is signed by siu.lead."""
    from core import harness, identity, mandate
    monkeypatch.setattr(identity, "KEYS_DIR", tmp_path / "keys")
    db = tmp_path / "ledger.db"
    pol = harness.load_policy()
    mandate.issue_policy(pol, "siu.lead", db=db)
    return {"db": db, "policy": pol}
