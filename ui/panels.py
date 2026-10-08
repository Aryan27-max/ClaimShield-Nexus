"""Case-page panels: signed-mandate chain with second signature, compliance obligations, PHI-masked members."""
from datetime import date

import pandas as pd
import streamlit as st

from core import compliance as CO
from core import harness, phi
from core import mandate as M
from core.policy_schema import regulatory_basis
from ui import common as C
from ui import style as U


def _flash(msg: str) -> None:
    st.session_state["flash"] = msg
    st.rerun()


def show_flash() -> None:
    if msg := st.session_state.pop("flash", None):
        st.success(msg)


def _state(step: dict | None) -> str:
    return "ok" if step and step["signature_ok"] and step["links_ok"] else "fail"


def authorisation(case_id: str, pol: dict) -> None:
    """Policy ✓ → Decision ✓ → Approval: only a different SIU lead sees the second-signature button."""
    st.subheader("Authorisation chain")
    dec = harness.decisions()
    dec = dec[dec.case_id == case_id]
    chain = {c["step"]: c for c in M.verify_chain(case_id)}
    if dec.empty or "decision" not in chain:
        ok, why, _ = M.policy_status(pol)
        U.html_line(U.steps([("Policy", "ok" if ok else "fail"), ("Decision", "todo"), ("Approval", "todo")]))
        st.caption(f"Policy: {why}. No signed decision for this case yet.")
        return
    last, dm = dec.iloc[-1], chain["decision"]["block"]
    dual = last.action in pol.get("dual_control_actions", [])
    approval = ("revoked" if last.status == "REVOKED" else _state(chain["approval"]) if "approval" in chain
                else "pending" if last.status == "PENDING_APPROVAL" else "na")
    U.html_line(U.steps([("Policy", _state(chain.get("policy"))), ("Decision", _state(chain["decision"])),
                         ("Approval", approval if dual or "approval" in chain else "na")]))
    st.caption(f"{last.action} signed by {dm['signer']} · key {dm['fingerprint']} · mandate {dm['mandate_hash'][:12]} · "
               f"status {last.status.replace('_', ' ').lower()}")
    if last.status != "PENDING_APPROVAL":
        return
    me, role = C.me(), C.my_role()
    if role == "siu_lead" and me != dm["signer"]:
        a, b = st.columns([1, 2])
        if a.button("Approve (second signature)", key="approve"):
            try:
                out = M.approve(int(last.decision_id), me, pol)
                _flash(f"Executed with second signature by {me} · mandate {out['mandate_hash'][:12]} · "
                       f"{len(out['obligations'])} obligation(s) created")
            except ValueError as e:
                st.error(str(e))
        with b.expander("Revoke this pending decision"):
            reason = st.text_input("Revocation reason", key="revoke_reason")
            if st.button("Revoke decision", key="revoke"):
                try:
                    M.revoke(dm["mandate_hash"], reason, me)
                    _flash(f"Decision revoked by {me}")
                except ValueError as e:
                    st.error(str(e))
    elif role == "siu_lead":
        st.info("Four-eyes: you signed this decision, so a different SIU lead must add the second signature.")
    else:
        st.info("Pending approval: an SIU lead other than the signer must add the second signature before it executes.")


def compliance(case: pd.Series, case_id: str, pol: dict, asof: date | None = None) -> None:
    """Obligations (status at today), regulatory basis and the completion / suspension / pause forms."""
    asof = asof or date.today()
    st.subheader("Regulatory basis")
    for topic, cite in regulatory_basis(pol, case.recommended_action, case.codes) or [("—", "routing action, no citation")]:
        st.markdown(f"- **{topic}**: {cite}")
    st.caption(f"Record retention setting: {pol.get('record_retention_years', '—')} years · "
               f"{pol.get('regulatory_basis', {}).get('retention', '')}. Not legal advice; state rules vary.")
    st.subheader("Obligations")
    ob = CO.obligations(asof=asof, case_id=case_id)
    if ob.empty:
        st.info("No obligations. They are created only when a human decision executes (REFER_TO_MFCU after the "
                "second signature, or any decision with reason OVERPAYMENT_IDENTIFIED), never from model scores.")
        return
    for o in ob.itertuples():
        extra = f" · ${o.amount:,.0f}" if pd.notna(o.amount) else ""
        done = f" · met {o.met_at} by {o.met_by}" + (f" ({o.determination})" if o.determination else "") if o.status == "MET" else ""
        U.html_line(U.chip(o.status, U.OBLIGATION_TONES[o.status]), f"**{o.label}** · due {o.due_date}{extra}{done}")
        st.caption(o.basis)
    doer = C.my_role() in CO.DOERS
    if not doer:
        st.info("Auditors can review obligations but cannot complete them.")
    open_ = ob[ob.status != "MET"]
    susp = open_[open_.type == "SUSPENSION_DETERMINATION"]
    if len(susp):
        with st.form("suspension", border=False):
            st.markdown("**Payment-suspension determination** (42 CFR 455.23)")
            det = st.radio("Determination", ["SUSPEND", "GOOD_CAUSE"], horizontal=True, key="determination")
            cause = st.selectbox("Good-cause reason (if not suspending)", list(CO.GOOD_CAUSE),
                                 format_func=CO.GOOD_CAUSE.get, key="good_cause")
            note = st.text_input("Documentation note (required)", key="susp_note")
            if st.form_submit_button("Record determination", disabled=not doer):
                try:
                    CO.record_suspension(int(susp.obligation_id.iloc[0]), det, C.me(), note, cause, asof=asof)
                    _flash(f"Suspension determination recorded: {det}")
                except ValueError as e:
                    st.error(str(e))
    rest = open_[open_.type != "SUSPENSION_DETERMINATION"]
    if len(rest):
        with st.form("mark_met", border=False):
            pick = st.selectbox("Obligation", rest.obligation_id.tolist(), key="ob_pick",
                                format_func=lambda i: f"#{i} {rest.set_index('obligation_id').label[i]}")
            note = st.text_input("Completion note (required)", key="met_note")
            if st.form_submit_button("Mark met", disabled=not doer):
                try:
                    CO.mark_met(int(pick), C.me(), note, asof=asof)
                    _flash(f"Obligation #{pick} marked met")
                except ValueError as e:
                    st.error(str(e))
    over = rest[rest.type == "OVERPAYMENT_RETURN"]
    if len(over):
        ok, why = CO.pause_allowed(pol)
        st.caption(f"Good-faith investigation pause: {why}")
        with st.form("pause", border=False):
            days = st.number_input("Pause days", 1, CO.MAX_PAUSE_DAYS, 90, key="pause_days", disabled=not ok)
            note = st.text_input("Pause justification", key="pause_note", disabled=not ok)
            if st.form_submit_button("Apply pause", disabled=not (ok and doer)):
                try:
                    CO.pause(int(over.obligation_id.iloc[0]), int(days), C.me(), note, pol)
                    _flash("Overpayment clock paused")
                except ValueError as e:
                    st.error(str(e))


def members(case: pd.Series, case_id: str) -> None:
    """Members on flagged claims, masked by default (token, age band, ZIP-3); reveal needs a reason and is ledgered."""
    st.subheader("Members on flagged claims")
    cl = C.claims(C._mtime(C.S.OUT / "claims.parquet"))
    ids = cl.member_id[cl.claim_id.isin(set(case.flagged_claim_ids))].unique()
    key = f"revealed_{case_id}"
    shown = phi.members_view(ids, C.table("members"), reveal=bool(st.session_state.get(key)))
    st.dataframe(shown, hide_index=True, width="stretch", height=240)
    if st.session_state.get(key):
        st.caption("Identifiers revealed for this case in this session; the access is recorded in the ledger.")
        return
    can = C.my_role() in phi.REVEALERS
    st.caption("Masked for minimum necessary (45 CFR 164.502(b)): keyed member tokens, age bands, 3-digit ZIP."
               + ("" if can else " Auditors can view masked data but cannot reveal it."))
    with st.form("reveal", border=False):
        reason = st.text_input("Reason for revealing member details", key="reveal_reason")
        if st.form_submit_button("Reveal member details", disabled=not can):
            try:
                phi.reveal(C.me(), case_id, reason)
                st.session_state[key] = True
                _flash("Member details revealed; phi_access recorded in the ledger")
            except ValueError as e:
                st.error(str(e))
