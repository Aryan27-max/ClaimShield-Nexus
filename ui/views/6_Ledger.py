"""Audit ledger: latest blocks, verify chain, tamper demo, reset."""
import json

import streamlit as st

from core import harness, ledger
from core import mandate as M
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
U.gap()

b1, b2, _ = st.columns([1, 1, 2])
if b1.button("Verify chain", key="verify", type="primary"):
    ok, bad = ledger.verify()
    U.result_card(ok, f"✓ Chain intact — {len(lg)} blocks verified." if ok else
                  f"✕ Chain broken at block {bad}. Every later block is untrusted.")
if b2.button("Verify signatures", key="verify_sigs"):
    sigs = M.verify_signatures()
    bad_sig = sigs[~sigs.signature_ok]
    U.result_card(bad_sig.empty, f"✓ {len(sigs)} signed mandates verified (Ed25519)." if bad_sig.empty else
                  f"✕ Signature invalid at block {int(bad_sig.idx.iloc[0])} ({bad_sig.event_type.iloc[0]}).")
    st.dataframe(sigs.assign(signature_ok=sigs.signature_ok.map({True: "✓", False: "✕"})), hide_index=True,
                 width="stretch")
    U.gap()

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
    U.gap()
    with U.card("decisions"):
        st.subheader("Human decisions")
        st.dataframe(d.iloc[::-1], hide_index=True, width="stretch")

U.gap()
with st.expander("Demo controls", expanded=bool(st.session_state.pop("open_reset", False))):
    a, b = st.columns(2)
    with a:
        st.markdown("**Simulate tamper** — edits a block's payload without re-hashing.")
        idx = st.number_input("Block", min_value=0, max_value=max(len(lg) - 1, 0), value=max(len(lg) - 1, 0), step=1)
        if st.button("Simulate tamper", key="danger_tamper", disabled=not len(lg)):
            ledger.tamper(int(idx))
            st.warning(f"Block {int(idx)} modified. Click Verify chain.")
    with b:
        st.markdown("**Reset demo ledger** — deletes all blocks and decisions, then re-logs a fresh pipeline run.")
        sure = st.checkbox("I understand this deletes the demo ledger")
        if st.button("Reset demo ledger", key="danger_reset", disabled=not sure):
            from core import pipeline
            with st.spinner("Resetting and re-running pipeline..."):
                pipeline.run_all(reset_ledger=True)
            st.cache_data.clear()
            st.rerun()
st.caption(C.FOOTER)
