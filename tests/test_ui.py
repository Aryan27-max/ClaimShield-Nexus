import pytest
from streamlit.testing.v1 import AppTest

from core import harness, ledger
from core import schema as S

APP = str(S.ROOT / "ui" / "app.py")
PAGES = ["views/1_Overview.py", "views/2_Queue.py", "views/3_Case.py", "views/4_Network.py", "views/5_Policy.py",
         "views/6_Ledger.py"]
pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    """Temporary ledger + demo keys; the shipped policy is signed by siu.lead (block 0)."""
    from core import identity, mandate
    db = tmp_path / "l.db"
    monkeypatch.setattr(ledger, "LEDGER_DB", db)
    monkeypatch.setattr(S, "LEDGER_DB", db)
    monkeypatch.setattr(identity, "KEYS_DIR", tmp_path / "keys")
    mandate.issue_policy(harness.load_policy(), "siu.lead", db=db)
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
    at = _app("views/3_Case.py")
    at.selectbox(key="reason_code").set_value("EVIDENCE_CORROBORATED")
    next(b for b in at.button if b.label == "Sign & submit").click()
    at.run()
    assert not at.exception and at.success, [e.value for e in at.error]
    d = harness.decisions(tmp_ledger)
    assert len(d) == 1 and d.user_id[0] == "inv.a" and d.status[0] == "PENDING_APPROVAL"
    events = list(ledger.read(tmp_ledger).event_type)
    assert events[0] == "policy_mandate" and events[-2:] == ["decision_mandate", "human_decision"]


def test_auditor_cannot_sign_decisions(tmp_ledger):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["identity"] = "auditor"
    at.run()
    at.switch_page("views/3_Case.py").run()
    assert next(b for b in at.button if b.label == "Sign & submit").disabled
    assert any("read-only" in i.value for i in at.info)


def test_ledger_verify_detects_tamper(tmp_ledger):
    ledger.append("system:test", "probe", {"x": 1}, tmp_ledger)
    ledger.tamper(0, tmp_ledger)
    at = _app("views/6_Ledger.py")
    at.button(key="verify").click()
    at.run()
    assert not at.exception
    assert any("broken at block 0" in m.value for m in at.markdown)


def test_case_brief_generates_and_logs(tmp_ledger):
    at = _app("views/3_Case.py")
    at.button(key="gen_brief").click().run()
    assert not at.exception, [e.value for e in at.exception]
    lg = ledger.read(tmp_ledger)
    assert list(lg.event_type) == ["policy_mandate", "case_viewed", "brief_generated"]
    assert any("Decision notice" in m.value for m in at.markdown)


def test_policy_preview_shows_changes(tmp_ledger):
    from eval.metrics import DEMO_THRESHOLDS
    at = _app("views/5_Policy.py")
    for path, v in DEMO_THRESHOLDS.items():
        next(s for s in at.slider if s.key.startswith(f"th_{path}_")).set_value(v)
    at.run()
    at.button(key="preview").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("case(s) change action" in m.value for m in list(at.markdown) + list(at.subheader))
    tiles = [m.value for m in at.markdown if "cs-tile" in m.value]
    assert any("Upcoding providers at PREPAY+" in t and ">1 → 5<" in t for t in tiles)
    assert any("Clean providers escalated" in t and ">0 → 0<" in t for t in tiles)
    assert len(ledger.read(tmp_ledger)) == 1  # only the signed policy; the preview writes nothing


def test_queue_open_case_renders_case_page(tmp_ledger):
    at = _app("views/2_Queue.py")
    first = at.selectbox[0].value
    next(b for b in at.button if b.label == "Open case").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == f"Case {first}"


def test_horizon_and_investigators_rerank(tmp_ledger):
    at = _app("views/2_Queue.py")  # AppTest runs only the page after switch_page: drive the sidebar state directly
    for h, n in [(30, 3), (60, 5), (90, 10)]:
        at.session_state["horizon"], at.session_state["investigators"] = h, n
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        assert any(f"{n} investigators · {30 * n} h this week · {h}-day horizon" in m.value for m in at.markdown)


def test_ledger_ui_tamper_then_verify_shows_broken_block(tmp_ledger):
    for i in range(3):
        ledger.append("system:test", "probe", {"i": i}, tmp_ledger)
    at = _app("views/6_Ledger.py")
    at.number_input[0].set_value(1)
    next(b for b in at.button if b.label == "Simulate tamper").click()
    at.run()
    at.button(key="verify").click()
    at.run()
    assert not at.exception
    assert any("broken at block 1" in m.value for m in at.markdown)


def test_policy_page_shows_validation_error_not_traceback(tmp_ledger, monkeypatch):
    from core import policy_edit as PE

    def reject(policy, values):
        if values:
            raise ValueError("invalid policy: abstain.statistical_min = 0.3 must be ...")
        return policy
    monkeypatch.setattr(PE, "with_thresholds", reject)
    at = _app("views/5_Policy.py")
    next(s for s in at.slider if s.key.startswith("th_abstain.statistical_min_")).set_value(0.3)
    at.run()
    assert not at.exception and any("not a valid policy" in e.value for e in at.error)
    assert at.button(key="preview").disabled


@pytest.mark.parametrize("page", ["views/1_Overview.py", "views/2_Queue.py", "views/3_Case.py", "views/4_Network.py"])
def test_no_cases_shows_friendly_empty_state(tmp_ledger, tmp_path, monkeypatch, page):
    import pandas as pd
    empty = tmp_path / "cases.parquet"
    pd.read_parquet(S.CASES).head(0).to_parquet(empty, index=False)
    monkeypatch.setattr(S, "CASES", empty)
    at = _app(page)
    assert not at.exception, [e.value for e in at.exception]
    if page != "views/4_Network.py":
        assert any("No cases under this data and policy" in i.value for i in at.info)


def test_deleted_policy_version_falls_back_to_available_one(tmp_ledger, tmp_path):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["policy_path"] = str(tmp_path / "harness_v7.yaml")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["policy_path"] == str(S.POLICY)
    assert any("harness_v7.yaml no longer exists" in w.value for w in at.warning)


def test_overview_without_ground_truth(tmp_ledger, monkeypatch):
    from ui import common
    monkeypatch.setattr(common, "has_ground_truth", lambda: False)
    at = _app("views/1_Overview.py")
    assert not at.exception, [e.value for e in at.exception]
    assert any("No ground truth available" in i.value for i in at.info)


def test_unexpected_page_error_is_shown_as_friendly_message(tmp_ledger, monkeypatch):
    from ui import common

    def boom():
        raise RuntimeError("disk unplugged")
    monkeypatch.setattr(common, "meta", boom)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert any("This page hit an unexpected error: disk unplugged" in e.value for e in at.error)


def test_full_dual_control_flow_obligations_and_tamper(tmp_ledger):
    from core import compliance as CO
    from core import mandate as M
    at = _app("views/3_Case.py")
    assert at.title[0].value == "Case RING-P0007"
    at.selectbox(key="reason_code").set_value("EVIDENCE_CORROBORATED")
    next(b for b in at.button if b.label == "Sign & submit").click().run()
    assert harness.decisions(tmp_ledger).status.iloc[-1] == "PENDING_APPROVAL"
    assert not [b for b in at.button if b.label == "Approve (second signature)"]
    at.session_state["identity"] = "siu.lead"
    at.run()
    at.button(key="approve").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert harness.decisions(tmp_ledger).status.iloc[-1] == "EXECUTED"
    assert set(CO.obligations(tmp_ledger).type) == {"SUSPENSION_DETERMINATION", "MFCU_REFERRAL", "MFCU_CERTIFICATION"}
    assert any("Written MFCU referral" in m.value for m in at.markdown)
    at.switch_page("views/6_Ledger.py").run()
    at.button(key="verify").click().run()
    assert any("Chain intact" in m.value for m in at.markdown)
    at.button(key="verify_sigs").click().run()
    assert any("signed mandates verified" in m.value for m in at.markdown)
    idx = int(M.verify_signatures(tmp_ledger).query("event_type == 'decision_mandate'").idx.iloc[0])
    at.number_input[0].set_value(idx)
    next(b for b in at.button if b.label == "Simulate tamper").click().run()
    at.button(key="verify").click().run()
    assert any(f"broken at block {idx}" in m.value for m in at.markdown)
    at.button(key="verify_sigs").click().run()
    assert any(f"Signature invalid at block {idx}" in m.value for m in at.markdown)


def test_case_viewed_logged_once_per_case_per_session(tmp_ledger):
    at = _app("views/3_Case.py")
    at.run()
    at.run()
    assert ledger.read(tmp_ledger).event_type.tolist().count("case_viewed") == 1
    at.selectbox[0].set_value(at.selectbox[0].options[1]).run()
    assert ledger.read(tmp_ledger).event_type.tolist().count("case_viewed") == 2


def test_tables_masked_and_reveal_is_audited(tmp_ledger):
    import pandas as pd
    from core import phi
    cases = pd.read_parquet(S.CASES)
    dup = cases[cases.codes.map(lambda c: "R01" in list(c))].case_id.iloc[0]
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["case_id"] = dup
    at.run()
    at.switch_page("views/3_Case.py").run()
    frames = [d.value for d in at.dataframe]
    ev = next(f for f in frames if "expected" in f.columns)
    assert not ev.value.astype(str).str.contains(phi.MEMBER_RE).any()
    mem = next(f for f in frames if "age_band" in f.columns)
    assert "member_id" not in mem.columns and mem.member.str.startswith("MBR-").all()
    at.text_input(key="reveal_reason").input("verify services with members")
    next(b for b in at.button if b.label == "Reveal member details").click().run()
    assert "phi_access" in ledger.read(tmp_ledger).event_type.tolist()
    assert any("member_id" in d.value.columns for d in at.dataframe)


def test_auditor_cannot_reveal(tmp_ledger):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["identity"] = "auditor"
    at.run()
    at.switch_page("views/3_Case.py").run()
    assert next(b for b in at.button if b.label == "Reveal member details").disabled


def test_sidebar_reset_demo_opens_ledger_controls(tmp_ledger):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert any("Public demo · synthetic data · shared state" in m.value for m in at.sidebar.markdown)
    next(b for b in at.sidebar.button if b.label == "Reset demo").click().run()
    assert not at.exception and at.title[0].value == "Audit Ledger"
    assert any(b.label == "Reset demo ledger" for b in at.button)
