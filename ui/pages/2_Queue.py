"""SIU queue: funnel strip + capacity-ranked cases."""
import streamlit as st

from ui import common as C

q, m = C.ranked(), C.meta()
f = m.get("funnel", {})
cap, used = q.attrs.get("capacity_hours", 0), q.attrs.get("used_hours", 0)

st.title("SIU Queue")
cols = st.columns(6)
cols[0].metric("Claims flagged", f"{f.get('claims_flagged', 0):,}")
cols[1].metric("Alerts", f.get("alerts", 0))
cols[2].metric("Cases", len(q))
cols[3].metric("In capacity", int((q.status == "in_capacity").sum()), help=f"{used:.0f} of {cap:.0f} investigator hours")
cols[4].metric("Deferred", int((q.status == "deferred").sum()), help="Shown, never dropped")
cols[5].metric("Needs more data", int((q.recommended_action == "NEEDS_MORE_DATA").sum()))
st.caption(f"Horizon {q.attrs.get('horizon')} d · {st.session_state.get('investigators')} investigators · "
           f"capacity {cap:.0f} h/week · policy {q.policy_hash.iloc[0][:10] if len(q) else '-'} · "
           "priority = p_fwa × $ at risk × severity_w × member_harm_w ÷ est_hours")

show_all = st.toggle("Include cases that need no investigator time (monitor / needs more data)", value=False)
view = q if show_all else q[q.status != "not_queued"]
table = view.assign(providers=view.providers.map(lambda p: ", ".join(p)))[
    ["rank", "case_id", "providers", "recommended_action", "confidence", "classes", "dollars_at_risk",
     "members_affected", "est_hours", "priority", "status"]]
event = st.dataframe(
    table, hide_index=True, width="stretch", height=520, on_select="rerun", selection_mode="single-row",
    column_config={
        "rank": st.column_config.NumberColumn("#", width="small"),
        "case_id": "Case", "providers": "Providers", "recommended_action": "Recommended",
        "confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=1, format="%.2f"),
        "classes": st.column_config.ListColumn("Evidence classes"),
        "dollars_at_risk": st.column_config.NumberColumn("$ at risk", format="dollar"),
        "members_affected": st.column_config.NumberColumn("Members"),
        "est_hours": st.column_config.NumberColumn("Est. h", format="%.0f"),
        "priority": st.column_config.NumberColumn("Priority", format="%.0f"),
        "status": "Status",
    })

rows = event.selection.rows if event and hasattr(event, "selection") else []
if rows:
    st.session_state["case_id"] = table.iloc[rows[0]].case_id
    st.switch_page("pages/3_Case.py")

c1, c2 = st.columns([3, 1])
pick = c1.selectbox("Open case", view.case_id.tolist(), label_visibility="collapsed")
if c2.button("Open case", type="primary", width="stretch"):
    st.session_state["case_id"] = pick
    st.switch_page("pages/3_Case.py")
st.caption(C.FOOTER)
