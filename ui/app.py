"""ClaimShield Nexus — Streamlit entry. Run: streamlit run ui/app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from ui import common as C  # noqa: E402
from ui import style as U  # noqa: E402

st.set_page_config(page_title="ClaimShield Nexus", page_icon=":shield:", layout="wide")
U.inject_css()

PAGES = [st.Page("pages/2_Queue.py", title="SIU Queue", icon=":material/format_list_numbered:", default=True),
         st.Page("pages/3_Case.py", title="Case", icon=":material/folder_open:"),
         st.Page("pages/6_Ledger.py", title="Audit Ledger", icon=":material/link:")]
nav = st.navigation(PAGES)

with st.sidebar:
    st.markdown("## ClaimShield Nexus")
    st.caption("Machines find evidence. Humans make decisions. The ledger proves it.")
    st.divider()
    files = C.policy_files()
    st.session_state.setdefault("policy_path", files[0] if files else str(C.S.POLICY))
    pol = C.policy(st.session_state["policy_path"])
    st.selectbox("Policy version", files, key="policy_path",
                 format_func=lambda p: f"v{C.policy(p)['version']} · {Path(p).stem} · {C.policy(p)['_hash'][:10]}")
    st.segmented_control("Risk horizon (days)", [30, 60, 90], default=90, key="horizon")
    st.caption("Queue uses the calibrated escalation model for this horizon.")
    st.slider("Investigators", 1, 10, value=pol["capacity"]["investigators"], key="investigators")
    st.caption(f"{pol['capacity']['hours_per_investigator_week']} h per investigator per week")
    if st.button("Re-run pipeline", help="Not needed for normal use; sliders only re-rank."):
        from core import pipeline
        with st.spinner("Running lenses, fusion and harness..."):
            pipeline.run_all()
        st.cache_data.clear()
        st.rerun()

if not C.S.CASES.exists():
    st.error("No cases yet. Run `python -m data.gen.synth && python -m core.pipeline` first.")
    st.stop()
nav.run()
