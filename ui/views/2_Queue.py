"""SIU queue: funnel + capacity tiles and the capacity-ranked case list."""
from datetime import date

import streamlit as st

from core import compliance as CO
from core import harness

from ui import common as C
from ui import style as U

q, m = C.ranked(), C.meta()
C.require_cases(q)
f = m.get("funnel", {})
cap, used = q.attrs.get("capacity_hours", 0), q.attrs.get("used_hours", 0)
n_over = int((q.status == "over_capacity").sum())

U.page_header("SIU Queue", f"{C.investigators()} investigators · {cap:.0f} h this week · "
                           f"{q.attrs.get('horizon')}-day horizon · policy {C.policy()['_hash'][:10]}")

tiles = [("Alerts", f.get("alerts", 0), "rules · anomaly · graph", None),
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
    dec = harness.decisions()
    pending = set(dec.case_id[dec.status == "PENDING_APPROVAL"])
    deadline = CO.next_deadlines(asof=date.today())
    table = view.assign(recommended_action=view.recommended_action.map(U.action_label),
                        status=[("pending approval" if c in pending else s.replace("_", " "))
                                for c, s in zip(view.case_id, view.status)],
                        next_deadline=view.case_id.map(deadline).fillna(""))[
        ["rank", "case_id", "recommended_action", "p_fwa", "confidence", "classes", "dollars_at_risk", "status",
         "next_deadline"]]
    event = st.dataframe(
        U.table_style(table, "recommended_action", "status"), hide_index=True, width="stretch", height=520,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "rank": st.column_config.NumberColumn("#", width=34),
            "case_id": st.column_config.TextColumn("Case", width=92),
            "recommended_action": st.column_config.TextColumn("Recommended", width=118),
            "p_fwa": st.column_config.ProgressColumn("P(escalation)", min_value=0, max_value=1, format="%.2f", width=90),
            "confidence": st.column_config.NumberColumn("Confidence", format="%.2f", width=75,
                                                        help="Evidence confidence = fused score × data completeness"),
            "classes": st.column_config.ListColumn("Evidence classes", width=178),
            "dollars_at_risk": st.column_config.NumberColumn("$ at risk", format="dollar", width=100),
            "status": st.column_config.TextColumn("Status", width=105),
            "next_deadline": st.column_config.TextColumn("Next deadline", width=95,
                                                         help="Earliest open compliance obligation"),
        })
    rows = event.selection.rows if event and hasattr(event, "selection") else []
    if rows:
        st.session_state["case_id"] = table.iloc[rows[0]].case_id
        st.switch_page("views/3_Case.py")
    c1, c2 = st.columns([4, 1])
    pick = c1.selectbox("Open case", view.case_id.tolist(), label_visibility="collapsed")
    if c2.button("Open case", width="stretch"):
        st.session_state["case_id"] = pick
        st.switch_page("views/3_Case.py")

st.caption("priority = P(escalation, horizon) × $ at risk × severity weight × member-harm weight ÷ est. hours. "
           "Must-take cases (MFCU or severity 5) fill capacity first. " + C.FOOTER)
