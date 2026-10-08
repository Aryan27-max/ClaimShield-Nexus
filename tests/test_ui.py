import pytest
from streamlit.testing.v1 import AppTest

from core import harness, ledger
from core import schema as S

APP = str(S.ROOT / "ui" / "app.py")
PAGES = ["pages/1_Overview.py", "pages/2_Queue.py", "pages/3_Case.py", "pages/4_Network.py", "pages/5_Policy.py",
         "pages/6_Ledger.py"]
pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    db = tmp_path / "l.db"
    monkeypatch.setattr(ledger, "LEDGER_DB", db)
    monkeypatch.setattr(S, "LEDGER_DB", db)
    return db


def _app(page: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    if page:
        at.switch_page(page)
        at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_pages_load(page, tmp_ledger):
    at = _app(page)
    assert not at.exception, [e.value for e in at.exception]
    assert at.title


def test_slider_reranks_without_error(tmp_ledger):
    at = _app()
    at.slider(key="investigators").set_value(8).run()
    assert not at.exception


def test_decision_submit_writes_decision_and_ledger(tmp_ledger):
    at = _app("pages/3_Case.py")
    at.text_input(key="user_id").input("tester")
    at.selectbox(key="reason_code").set_value("EVIDENCE_CORROBORATED")
    next(b for b in at.button if b.label == "Record decision").click()
    at.run()
    assert not at.exception and at.success, [e.value for e in at.error]
    assert len(harness.decisions(tmp_ledger)) == 1
    lg = ledger.read(tmp_ledger)
    assert len(lg) == 1 and lg.event_type[0] == "human_decision"


def test_decision_without_user_is_rejected(tmp_ledger):
    at = _app("pages/3_Case.py")
    next(b for b in at.button if b.label == "Record decision").click()
    at.run()
    assert at.error and len(ledger.read(tmp_ledger)) == 0


def test_ledger_verify_detects_tamper(tmp_ledger):
    ledger.append("system:test", "probe", {"x": 1}, tmp_ledger)
    ledger.tamper(0, tmp_ledger)
    at = _app("pages/6_Ledger.py")
    at.button(key="verify").click()
    at.run()
    assert not at.exception
    assert any("broken at block 0" in m.value for m in at.markdown)


def test_case_brief_generates_and_logs(tmp_ledger):
    at = _app("pages/3_Case.py")
    at.button(key="gen_brief").click().run()
    assert not at.exception, [e.value for e in at.exception]
    lg = ledger.read(tmp_ledger)
    assert len(lg) == 1 and lg.event_type[0] == "brief_generated"
    assert any("Decision notice" in m.value for m in at.markdown)


def test_policy_preview_shows_changes(tmp_ledger):
    from eval.metrics import DEMO_THRESHOLDS
    at = _app("pages/5_Policy.py")
    for path, v in DEMO_THRESHOLDS.items():
        next(s for s in at.slider if s.key.startswith(f"th_{path}_")).set_value(v)
    at.run()
    at.button(key="preview").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("case(s) change action" in m.value for m in list(at.markdown) + list(at.subheader))
    assert len(ledger.read(tmp_ledger)) == 0
