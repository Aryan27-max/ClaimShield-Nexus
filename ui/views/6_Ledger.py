"""Audit ledger: latest blocks, verify chain, tamper demo, reset."""
import json

import streamlit as st

from core import harness, ledger
from ui import common as C
from ui import style as U

U.page_header("Audit Ledger", "Append-only SHA-256 hash chain · hash = SHA256(prev_hash ‖ payload_sha ‖ ts ‖ actor ‖ event_type)")

lg = ledger.read()
m = C.meta()
tiles = [("Blocks", len(lg)), ("Human decisions", int((lg.event_type == "human_decision").sum()) if len(lg) else 0),
         ("Policy hash", m.get("policy_hash", "-")[:10]), ("Cases Merkle root", m.get("cases_merkle_root", "-")[:10]),
         ("Model params", m.get("model_params_hash", "-")[:10])]
for col, (label, value) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, small=isinstance(value, str))
st.write("")

if st.button("Verify chain", key="verify"):
    ok, bad = ledger.verify()
    U.result_card(ok, f"✓ Chain intact — {len(lg)} blocks verified." if ok else
                  f"✕ Chain broken at block {bad}. Every later block is untrusted.")
    st.write("")

with U.card("chain"):
    st.subheader("Latest 50 blocks")
    if len(lg):
        view = lg.tail(50).iloc[::-1].assign(
            payload=lambda d: d.payload_json.map(lambda s: json.dumps(json.loads(s))[:140]),
            prev_hash=lambda d: d.prev_hash.str[:12], hash=lambda d: d.hash.str[:12])
        st.dataframe(view[["idx", "ts", "actor", "event_type", "prev_hash", "hash", "payload"]],
                     hide_index=True, width="stretch", height=420)

d = harness.decisions()
if len(d):
    st.write("")
    with U.card("decisions"):
        st.subheader("Human decisions")
        st.dataframe(d.iloc[::-1], hide_index=True, width="stretch")

st.write("")
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
st.caption(C.FOOTER)
