"""Audit ledger: latest blocks, verify chain, tamper demo, reset."""
import json

import streamlit as st

from core import harness, ledger
from core import mandate as M
from ui import common as C
from ui import style as U

U.page_header("Audit Ledger", "Prove nothing was altered: verify the hash chain and every signature. Every lens run, "
                              "policy, decision, brief and case view is recorded here.")

lg = ledger.read()
m = C.meta()
tiles = [("Blocks", len(lg)), ("Human decisions", int((lg.event_type == "human_decision").sum()) if len(lg) else 0),
         ("Policy hash", m.get("policy_hash", "-")[:10]), ("Cases Merkle root", m.get("cases_merkle_root", "-")[:10]),
         ("Model params", m.get("model_params_hash", "-")[:10])]
for col, (label, value) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, small=isinstance(value, str))
U.gap()

with U.button_row("verify"):
    do_chain = st.button("Verify chain", key="verify", type="primary", icon=":material/link:")
    do_sigs = st.button("Verify signatures", key="verify_sigs", icon=":material/verified:")
st.caption("Each block stores SHA256(previous hash ‖ payload hash ‖ time ‖ actor ‖ event); signed mandates also carry "
           "an Ed25519 signature and key fingerprint.")
if do_chain:
    ok, bad = ledger.verify()
    st.toast("Chain intact" if ok else f"Chain broken at block {bad}", icon=":material/link:")
    U.result_card(ok, f"✓ Chain intact — {len(lg)} blocks verified." if ok else
                  f"✕ Chain broken at block {bad}. Every later block is untrusted.")
if do_sigs:
    sigs = M.verify_signatures()
    bad_sig = sigs[~sigs.signature_ok]
    st.toast("All signatures valid" if bad_sig.empty else "A signature failed", icon=":material/verified:")
    U.result_card(bad_sig.empty, f"✓ {len(sigs)} signed mandates verified (Ed25519)." if bad_sig.empty else
                  f"✕ Signature invalid at block {int(bad_sig.idx.iloc[0])} ({bad_sig.event_type.iloc[0]}).")
    st.dataframe(sigs.assign(signature_ok=sigs.signature_ok.map({True: "✓", False: "✕"})), hide_index=True,
                 width="stretch")
    U.gap()

with U.card("chain"):
    st.subheader("Latest 50 blocks")
    if len(lg):
        view = lg.tail(50).iloc[::-1]
        view = view.assign(time=view.ts.str[:19].str.replace("T", " ") + " UTC",
                           summary=[C.ledger_summary(e, json.loads(p)) for e, p in zip(view.event_type, view.payload_json)],
                           prev_hash=view.prev_hash.str[:12], hash=view.hash.str[:12])
        st.dataframe(view[["idx", "time", "actor", "event_type", "summary", "prev_hash", "hash"]], hide_index=True,
                     width="stretch", height=420, column_config={
                         "idx": st.column_config.NumberColumn("#", width=40), "time": st.column_config.TextColumn(width=160),
                         "actor": st.column_config.TextColumn(width=110), "event_type": st.column_config.TextColumn(
                             "event", width=125), "summary": st.column_config.TextColumn(width=300),
                         "prev_hash": st.column_config.TextColumn("prev hash", width=105),
                         "hash": st.column_config.TextColumn(width=105)})
        with st.expander("Raw payload of the latest block"):
            st.json(json.loads(lg.payload_json.iloc[-1]))

d = harness.decisions()
U.gap()
with U.card("decisions"):
    st.subheader("Human decisions")
    if len(d):
        st.dataframe(d.iloc[::-1], hide_index=True, width="stretch")
    else:
        U.callout("No human decisions yet. Open a case from the SIU Queue and sign one; it will appear here with its "
                  "mandate hash.", "gray", "inbox")

U.gap()
with st.expander("Demo controls", expanded=bool(st.session_state.pop("open_reset", False))):
    a, b = st.columns(2)
    with a:
        st.markdown("**Simulate tamper**: edits one block's payload without re-hashing (demo only).")
        idx = st.number_input("Block", min_value=0, max_value=max(len(lg) - 1, 0), value=max(len(lg) - 1, 0), step=1)
        agree = st.checkbox("I understand this breaks the chain until the demo is reset", key="confirm_tamper")
        if st.button("Simulate tamper", key="danger_tamper", disabled=not (len(lg) and agree)):
            ledger.tamper(int(idx))
            st.toast(f"Block {int(idx)} modified", icon=":material/warning:")
            st.warning(f"Block {int(idx)} modified. Click Verify chain and Verify signatures.")
    with b:
        st.markdown("**Reset demo ledger**: deletes all blocks and decisions, then re-logs a fresh pipeline run.")
        sure = st.checkbox("I understand this deletes the demo ledger")
        if st.button("Reset demo ledger", key="danger_reset", disabled=not sure):
            from core import pipeline
            with st.spinner("Resetting and re-running pipeline..."):
                pipeline.run_all(reset_ledger=True)
            st.cache_data.clear()
            st.rerun()
st.caption(C.FOOTER)
