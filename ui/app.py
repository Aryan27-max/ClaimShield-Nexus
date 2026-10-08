"""ClaimShield Nexus — Streamlit entry. Run: streamlit run ui/app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from ui import common as C  # noqa: E402
from ui import style as U  # noqa: E402

st.set_page_config(page_title="ClaimShield Nexus", page_icon=":shield:", layout="wide")
U.inject_css()

PAGES = [st.Page("views/1_Overview.py", title="Overview", icon=":material/insights:", default=True),
         st.Page("views/2_Queue.py", title="SIU Queue", icon=":material/format_list_numbered:"),
         st.Page("views/3_Case.py", title="Case", icon=":material/folder_open:"),
         st.Page("views/4_Network.py", title="Network", icon=":material/hub:"),
         st.Page("views/5_Policy.py", title="Policy", icon=":material/gavel:"),
         st.Page("views/6_Ledger.py", title="Audit Ledger", icon=":material/link:")]
nav = st.navigation(PAGES)

with st.sidebar:
    st.markdown("## ClaimShield Nexus")
    st.caption("Machines find evidence. Humans make decisions. The ledger proves it.")
    st.divider()
    files = C.policy_files()
    if st.session_state.get("pending_policy") in files:  # set by the Policy page after "Save as new version"
        st.session_state["policy_path"] = st.session_state.pop("pending_policy")
    gone = st.session_state.get("policy_path")
    if gone not in files:  # first visit, or the selected version file was removed (e.g. a demo reset)
        st.session_state["policy_path"] = files[0] if files else str(C.S.POLICY)
        if gone:
            st.warning(f"{Path(gone).name} no longer exists; using {Path(st.session_state['policy_path']).name}.")
    try:
        pol = C.policy(st.session_state["policy_path"])
    except (OSError, ValueError) as e:
        st.error(f"Policy cannot be loaded: {e}")
        st.stop()
    st.selectbox("Policy version", files, key="policy_path", format_func=C.policy_label)
    st.segmented_control("Risk horizon (days)", [30, 60, 90], default=90, key="horizon")
    st.caption("Queue uses the calibrated escalation model for this horizon.")
    st.slider("Investigators", 1, 10, value=pol["capacity"]["investigators"], key="investigators")
    st.caption(f"{pol['capacity']['hours_per_investigator_week']} h per investigator per week")
    if st.button("Re-run pipeline", help="Not needed for normal use; sliders only re-rank."):
        from core import pipeline
        try:
            with st.spinner("Running lenses, fusion and harness..."):
                pipeline.run_all()
            st.cache_data.clear()
            st.rerun()
        except (OSError, ValueError) as e:
            st.error(f"Pipeline did not run: {e}")

if not C.S.CASES.exists():
    st.error("No cases yet. Run `python -m data.gen.synth && python -m core.pipeline` first.")
    st.stop()
try:
    nav.run()
except Exception as e:  # Streamlit's rerun / stop signals derive from BaseException and pass through
    C.show_error(e, "This page hit an unexpected error")
