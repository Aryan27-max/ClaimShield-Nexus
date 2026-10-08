import pytest
from streamlit.testing.v1 import AppTest

from core import harness
from core import schema as S
from tests.test_ui import APP, PAGES, tmp_ledger  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


def _themed(theme: str, page: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["theme"] = theme
    at.run()
    if page:
        at.switch_page(page).run()
    return at


def _texts(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("page", PAGES)
def test_pages_load_in_both_themes(page, theme, tmp_ledger):
    at = _themed(theme, page)
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["theme"] == theme and at.title


def test_theme_choice_persists_across_reruns_and_navigation(tmp_ledger):
    at = _themed("dark")
    at.query_params.pop("theme")  # page navigation drops query params
    at.run()
    assert at.session_state["theme"] == "dark"
    at.switch_page("views/4_Network.py").run()
    assert at.session_state["theme"] == "dark" and not at.exception
    assert any('const t = \\"dark\\"' in str(getattr(e, "proto", "")) for e in at.sidebar)  # choice kept in URL


def test_theme_query_param_switches_back_to_light(tmp_ledger):
    at = _themed("dark")
    at.query_params["theme"] = "light"
    at.run()
    assert at.session_state["theme"] == "light"


def test_invalid_theme_param_follows_system(tmp_ledger):
    at = _themed("purple")
    assert "theme" not in at.session_state and not at.exception


def test_toggle_links_carry_native_theme_param(tmp_ledger):
    at = _themed("light")
    toggle = next(m.value for m in at.sidebar.markdown if 'class="cs-segbar"' in m.value)
    assert "?theme=dark&embed_options=dark_theme" in toggle and 'target="_self"' in toggle


def test_empty_states_case_and_ledger(tmp_ledger):
    at = _themed("dark", "views/3_Case.py")
    assert "No decisions on this case yet." in _texts(at)
    at.switch_page("views/6_Ledger.py").run()
    assert "No human decisions yet" in _texts(at)


def test_verify_and_preview_show_toasts(tmp_ledger):
    at = _themed("dark", "views/6_Ledger.py")
    at.button(key="verify").click().run()
    assert any("Chain intact" in t.value for t in at.toast)


def test_tamper_requires_confirmation(tmp_ledger):
    at = _themed("dark", "views/6_Ledger.py")
    tamper = next(b for b in at.button if b.label == "Simulate tamper")
    assert tamper.disabled
    at.checkbox(key="confirm_tamper").check().run()
    assert not next(b for b in at.button if b.label == "Simulate tamper").disabled


def test_demo_flow_in_dark_mode_signs_mfcu_within_five_clicks(tmp_ledger):
    """Overview -> Open SIU Queue -> Open case -> reason -> Sign & submit (Record decision is an in-page jump)."""
    at = _themed("dark")
    next(b for b in at.button if b.label == "Open SIU Queue").click().run()
    assert at.title[0].value == "SIU Queue"
    at.switch_page("views/2_Queue.py")  # AppTest keeps the start page after an in-script switch_page
    next(b for b in at.button if b.label == "Open case").click().run()
    assert at.title[0].value == "Case RING-P0007"
    assert at.selectbox(key="action").value == "REFER_TO_MFCU"
    at.switch_page("views/3_Case.py")
    at.selectbox(key="reason_code").set_value("EVIDENCE_CORROBORATED")
    next(b for b in at.button if b.label == "Sign & submit").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert harness.decisions(tmp_ledger).action.iloc[-1] == "REFER_TO_MFCU"
    assert any("Decision signed" in t.value for t in at.toast)
    assert any(b.label == "View in Audit Ledger" for b in at.button)
    assert at.session_state["theme"] == "dark"
