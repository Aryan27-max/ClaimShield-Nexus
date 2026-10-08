"""SIU queue: funnel + capacity tiles and the capacity-ranked case list."""
import streamlit as st

from ui import common as C
from ui import style as U

q, m = C.ranked(), C.meta()
f = m.get("funnel", {})
cap, used = q.attrs.get("capacity_hours", 0), q.attrs.get("used_hours", 0)
n_over = int((q.status == "over_capacity").sum())

U.page_header("SIU Queue", f"{st.session_state.get('investigators')} investigators · {cap:.0f} h this week · "
                           f"{q.attrs.get('horizon')}-day horizon · policy {q.policy_hash.iloc[0][:10]}")

tiles = [("Claims flagged", f"{f.get('claims_flagged', 0):,}", "raw rule / lens hits", None),
         ("Alerts", f.get("alerts", 0), "rules · anomaly · graph", None),
         ("Cases", len(q), f"{int((q.status != 'not_queued').sum())} need investigator time", None),
         ("In capacity", int((q.status == "in_capacity").sum()), f"{used:.0f} of {cap:.0f} h", "green"),
         ("Over capacity", n_over, "must-take · escalate", "red" if n_over else None),
         ("Deferred", int((q.status == "deferred").sum()), "shown, never dropped", "orange"),
         ("Weeks to clear", q.attrs.get("weeks_to_clear"), "queued h ÷ weekly h", None)]
for col, (label, value, delta, tone) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, delta, tone)
st.write("")
if n_over:
    U.result_card(False, f"{n_over} must-take case(s) exceed this week's capacity — escalate to SIU lead.")
    st.write("")

with U.card("queue"):
    top = st.columns([3, 2])
    with top[0]:
        U.html_line(*(U.action_badge(a) for a in U.ACTION_COLORS))
    show_all = top[1].toggle("Include monitor / needs-more-data cases", value=False)
    view = q if show_all else q[q.status != "not_queued"]
    table = view.assign(providers=view.providers.map(lambda p: ", ".join(p)),
                        recommended_action=view.recommended_action)[
        ["rank", "case_id", "providers", "recommended_action", "p_fwa", "confidence", "classes", "dollars_at_risk",
         "members_affected", "est_hours", "status"]]
    event = st.dataframe(
        U.table_style(table, "recommended_action", "status"), hide_index=True, width="stretch", height=520,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "rank": st.column_config.NumberColumn("#", width="small"),
            "case_id": "Case", "providers": "Providers", "recommended_action": "Recommended",
            "p_fwa": st.column_config.ProgressColumn("P(escalation)", min_value=0, max_value=1, format="%.2f"),
            "confidence": st.column_config.NumberColumn("Evidence conf.", format="%.2f"),
            "classes": st.column_config.ListColumn("Evidence classes"),
            "dollars_at_risk": st.column_config.NumberColumn("$ at risk", format="dollar"),
            "members_affected": st.column_config.NumberColumn("Members"),
            "est_hours": st.column_config.NumberColumn("Est. h", format="%.0f"),
            "status": "Status",
        })
    rows = event.selection.rows if event and hasattr(event, "selection") else []
    if rows:
        st.session_state["case_id"] = table.iloc[rows[0]].case_id
        st.switch_page("pages/3_Case.py")
    c1, c2 = st.columns([4, 1])
    pick = c1.selectbox("Open case", view.case_id.tolist(), label_visibility="collapsed")
    if c2.button("Open case", width="stretch"):
        st.session_state["case_id"] = pick
        st.switch_page("pages/3_Case.py")

st.caption("priority = P(escalation, horizon) × $ at risk × severity weight × member-harm weight ÷ est. hours. "
           "Must-take cases (MFCU or severity 5) fill capacity first. " + C.FOOTER)
