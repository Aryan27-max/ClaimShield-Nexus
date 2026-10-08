"""Audit ledger: latest blocks, verify chain, tamper demo, reset."""
import json

import streamlit as st

from core import harness, ledger
from ui import common as C

st.title("Audit Ledger")
st.caption("Append-only SHA-256 hash chain: hash = SHA256(prev_hash ‖ payload_sha ‖ ts ‖ actor ‖ event_type).")

lg = ledger.read()
c = st.columns(4)
c[0].metric("Blocks", len(lg))
c[1].metric("Human decisions", int((lg.event_type == "human_decision").sum()) if len(lg) else 0)
c[2].metric("Policy", C.meta().get("policy_hash", "-")[:10])
c[3].metric("Cases Merkle root", C.meta().get("cases_merkle_root", "-")[:10])

if st.button("Verify chain", type="primary"):
    ok, bad = ledger.verify()
    if ok:
        st.success(f"Chain OK — {len(lg)} blocks verified.")
    else:
        st.error(f"Chain broken at block {bad}.")

if len(lg):
    view = lg.tail(50).iloc[::-1].assign(
        payload=lambda d: d.payload_json.map(lambda s: json.dumps(json.loads(s))[:140]),
        prev_hash=lambda d: d.prev_hash.str[:12], hash=lambda d: d.hash.str[:12])
    st.dataframe(view[["idx", "ts", "actor", "event_type", "prev_hash", "hash", "payload"]],
                 hide_index=True, width="stretch", height=420)

with st.expander("Demo controls"):
    a, b = st.columns(2)
    with a:
        st.markdown("**Simulate tamper** — edits a block's payload without re-hashing.")
        idx = st.number_input("Block", min_value=0, max_value=max(len(lg) - 1, 0), value=max(len(lg) - 1, 0), step=1)
        if st.button("Simulate tamper", disabled=not len(lg)):
            ledger.tamper(int(idx))
            st.warning(f"Block {int(idx)} modified. Click Verify chain.")
    with b:
        st.markdown("**Reset demo ledger** — deletes all blocks and decisions, then re-logs a fresh pipeline run.")
        sure = st.checkbox("I understand this deletes the demo ledger")
        if st.button("Reset demo ledger", disabled=not sure):
            from core import pipeline
            with st.spinner("Resetting and re-running pipeline..."):
                pipeline.run_all(reset_ledger=True)
            st.cache_data.clear()
            st.rerun()

d = harness.decisions()
if len(d):
    st.subheader("Decisions")
    st.dataframe(d.iloc[::-1], hide_index=True, width="stretch")
st.caption(C.FOOTER)
