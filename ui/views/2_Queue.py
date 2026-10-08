"""SIU queue: funnel + capacity tiles and the capacity-ranked case list."""
from datetime import date

import streamlit as st

from core import compliance as CO
from core import harness

from ui import common as C
from ui import fmt
from ui import style as U

q, m = C.ranked(), C.meta()
C.require_cases(q)
f = m.get("funnel", {})
cap, used = q.attrs.get("capacity_hours", 0), q.attrs.get("used_hours", 0)
n_over = int((q.status == "over_capacity").sum())

U.page_header("SIU Queue", f"Pick the next case to work, ranked to fit this week's hours · "
                           f"{C.investigators()} investigators · {cap:.0f} h · {q.attrs.get('horizon')}\u2011day horizon")

tiles = [("Alerts", f.get("alerts", 0), "rules · anomaly · graph", None),
         ("Cases", len(q), f"{int((q.status != 'not_queued').sum())} need investigator time", None),
         ("In capacity", int((q.status == "in_capacity").sum()), f"{used:.0f} of {cap:.0f} h", "green"),
         ("Over capacity", n_over, "must-take · escalate", "red" if n_over else None),
         ("Deferred", int((q.status == "deferred").sum()), "shown, never dropped", "orange"),
         ("Weeks to clear", q.attrs.get("weeks_to_clear"), "queued h ÷ weekly h", None)]
for col, (label, value, delta, tone) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, delta, tone)
U.gap()
if n_over:
    U.callout(f"{fmt.plural(n_over, 'must-take case')} {'exceeds' if n_over == 1 else 'exceed'} this week's capacity. "
              "Escalate to the SIU lead, or add investigators in the sidebar.", "red", "warning")
    U.gap()

with U.card("queue"):
    st.session_state.setdefault("queue_show_all", False)
    view = q if st.session_state["queue_show_all"] else q[q.status != "not_queued"]
    c1, c2, c3 = st.columns([2, 1, 2], vertical_alignment="bottom")
    pick = c1.selectbox("Case to open", view.case_id.tolist(), help="Ranked order; the top case is preselected.")
    if c2.button("Open case", type="primary", width="stretch"):
        st.session_state["case_id"] = pick
        st.switch_page("views/3_Case.py")
    c3.toggle("Show monitor & needs-data cases", key="queue_show_all",
              help="Cases that use no investigator time: routine monitoring, or evidence too weak to act on.")
    U.html_line(*(U.action_badge(a) for a in U.ACTION_COLORS))
    st.caption("Tip: click a row to open that case.")
    dec = harness.decisions()
    pending = set(dec.case_id[dec.status == "PENDING_APPROVAL"])
    deadline = CO.next_deadlines(asof=date.today())
    table = view.assign(recommended_action=view.recommended_action.map(U.action_label),
                        status=[("pending approval" if c in pending else s.replace("_", " "))
                                for c, s in zip(view.case_id, view.status)],
                        next_deadline=view.case_id.map(deadline).map(fmt.day).fillna(""))[
        ["rank", "case_id", "recommended_action", "p_fwa", "confidence", "classes", "dollars_at_risk", "status",
         "next_deadline"]]
    event = st.dataframe(
        U.table_style(table, "recommended_action", "status"), hide_index=True, width="stretch", height=520,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "rank": st.column_config.NumberColumn("#", width=30),
            "case_id": st.column_config.TextColumn("Case", width=84),
            "recommended_action": st.column_config.TextColumn("Recommended", width=104,
                                                              help="Highest action the signed policy allows; a person decides"),
            "p_fwa": st.column_config.ProgressColumn("Escalation", min_value=0, max_value=1, format="percent", width=80,
                                                     help="Calibrated chance of a strong alert or confirmed case within "
                                                          "the horizon (a forecast, never evidence)"),
            "confidence": st.column_config.NumberColumn("Confidence", format="percent", step=0.001, width=72,
                                                        help="Evidence confidence = fused score × data completeness"),
            "classes": st.column_config.ListColumn("Evidence classes", width=190),
            "dollars_at_risk": st.column_config.NumberColumn("$ at risk", format="dollar", step=1, width=84),
            "status": st.column_config.TextColumn("Status", width=92),
            "next_deadline": st.column_config.TextColumn("Next due", width=80,
                                                         help="Earliest open compliance obligation"),
        })
    rows = event.selection.rows if event and hasattr(event, "selection") else []
    if rows:
        st.session_state["case_id"] = table.iloc[rows[0]].case_id
        st.switch_page("views/3_Case.py")

st.caption("Priority = chance of escalation × $ at risk × severity weight × member-harm weight ÷ estimated hours. "
           "Must-take cases (MFCU or severity 5) get hours first. " + C.FOOTER)
