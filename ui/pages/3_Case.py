"""Case view: evidence, risk forecast, timeline, ego network, limitations, rule trace, human decision form."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import harness
from ui import common as C
from ui import style as U

q = C.ranked()
ids = q.case_id.tolist()
cur = st.session_state.get("case_id")
case_id = st.selectbox("Case", ids, index=ids.index(cur) if cur in ids else 0)
st.session_state["case_id"] = case_id
r = q.set_index("case_id").loc[case_id]
pol = C.policy()

who = f"Ring of {r.n_providers} providers" if r.case_type == "ring" else "Provider"
U.page_header(f"Case {case_id}", f"{who} {', '.join(r.providers)} · {', '.join(r.provider_types)} · "
                                 f"rank #{r['rank']} · {r.status.replace('_', ' ')}")
U.html_line(U.action_badge(r.recommended_action), "&nbsp;", U.class_chips(r.classes))
st.write("")
tiles = [("Evidence confidence", f"{r.confidence:.2f}", f"fused {r.fused_score:.2f} × completeness {r.completeness:.2f}"),
         (f"P(escalation, {q.attrs.get('horizon')} d)", f"{r.p_fwa:.0%}", "calibrated model" if r.has_model_score
          else "no model score"),
         ("$ at risk", f"${r.dollars_at_risk:,.0f}", f"{r.n_flagged_claims:,} flagged claims"),
         ("Members affected", f"{r.members_affected:,}", f"{r.vulnerable_share:.0%} under 18 or 65+"),
         ("Est. hours", f"{r.est_hours:.0f}", "must-take" if r.must_take else "")]
for col, (label, value, delta) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, delta)
st.write("")
if r.recommended_action == "NEEDS_MORE_DATA":
    st.warning("Needs more data — missing evidence class(es): **" + ", ".join(r.missing_classes) +
               "**. Gather corroborating evidence before any escalation.")
if r.requires_human:
    st.info("REFER_TO_MFCU is allowed for this case and always requires a human decision.")

tab_ev, tab_risk, tab_tl, tab_net, tab_why = st.tabs(["Evidence", "Risk forecast", "Timeline", "Network",
                                                     "Why this action"])
with tab_ev, U.card("evidence"):
    ev = pd.DataFrame(list(r.evidence))
    if len(ev):
        st.dataframe(ev[["claim_id", "field", "value", "expected", "lens", "class", "code", "entity_id"]],
                     hide_index=True, width="stretch", height=360)
    d = st.columns(3)
    for col, (label, v) in zip(d, [("Deterministic $ (flagged claims)", r.dollars_deterministic),
                                   ("Structural $ (flagged claims)", r.dollars_structural),
                                   ("Statistical $ (excess vs peers)", r.dollars_statistical)]):
        with col:
            U.metric_tile(label, f"${v:,.0f}")
    st.caption(f"{len(r.alert_ids)} alerts ({', '.join(r.codes)}). $ at risk = paid on the union of claim-level "
               "flags; statistical excess only counts when no claim-level evidence exists.")

with tab_risk, U.card("risk"):
    if r.has_model_score:
        hs = [30, 60, 90]
        a, b = st.columns([3, 2])
        fig = go.Figure(go.Bar(x=[f"{h} days" for h in hs], y=[r[f"p_{h}"] for h in hs], marker_color=U.ACCENT,
                               text=[f"{r[f'p_{h}']:.0%}" for h in hs], textposition="outside", width=0.5))
        fig.update_layout(template=U.plotly_template(), height=300,
                          yaxis=dict(range=[0, 1.15], tickformat=".0%", title="P(escalation)"))
        a.plotly_chart(fig, width="stretch")
        with b:
            st.markdown(f"**Top drivers** · provider {r.driver_provider}")
            for d in r.drivers:
                st.markdown(f"- {d['label'].capitalize()}: **{d['value']}**")
        st.caption("Calibrated LightGBM forecast of a strong alert or confirmed investigation within the horizon. "
                   "A forecast is not evidence: it never counts toward FULL_INVESTIGATION or MFCU.")
    else:
        st.info("No model score for this provider; the queue uses fused confidence.")

with tab_tl, U.card("timeline"):
    c = C.claims(C._mtime(C.S.OUT / "claims.parquet"))
    c = c[c.provider_id.isin(list(r.providers))]
    c = c.assign(month=c.service_date.dt.to_period("M").dt.to_timestamp(),
                 flagged=c.claim_id.isin(set(r.flagged_claim_ids)))
    tl = c.groupby(["month", "flagged"]).paid_amt.sum().unstack(fill_value=0).reindex(columns=[False, True], fill_value=0)
    fig = go.Figure([go.Bar(x=tl.index, y=tl[False], name="Paid (not flagged)", marker_color=U.ACCENT_SOFT),
                     go.Bar(x=tl.index, y=tl[True], name="Paid (flagged)", marker_color=U.RED)])
    fig.update_layout(template=U.plotly_template(), barmode="stack", height=360, yaxis_title="Paid $ per month")
    st.plotly_chart(fig, width="stretch")

with tab_net, U.card("network"):
    if st.toggle("Show ego network (≤ 150 nodes)", value=False, key=f"net_{case_id}"):
        html, n = C.ego_html(case_id if r.case_type == "ring" else r.providers[0], list(r.providers))
        st.caption(f"{n} nodes · red = case providers and referral edges · blue providers · orange owners · "
                   "green addresses · purple banks · grey members")
        st.iframe(html, height=540)

with tab_why, U.card("why"):
    st.subheader("Limitations")
    for lim in r.limitations:
        st.markdown(f"- {lim}")
    st.subheader("Why not a higher action")
    st.code("\n".join(r.rule_trace), language=None)
    st.caption(f"Policy v{r.policy_version} · {r.policy_hash[:16]} · allowed: {', '.join(r.allowed_actions)}")

st.write("")
with U.card("decision"):
    st.subheader("Human decision")
    with st.form("decision", clear_on_submit=False, border=False):
        a, b = st.columns(2)
        user_id = a.text_input("Investigator user_id", key="user_id")
        action = b.selectbox("Action (allowed by policy)", list(r.allowed_actions), key="action")
        reasons = pol["reason_codes"]
        reason = a.selectbox("Reason code", list(reasons), format_func=lambda k: f"{k} — {reasons[k]}", key="reason_code")
        note = b.text_area("Note", key="note", height=68)
        submitted = st.form_submit_button("Record decision")
    if submitted:
        try:
            out = harness.decide(case_id, action, user_id, reason, note, cases=q, policy=pol)
            st.success(f"Decision recorded: {action} on {case_id} → ledger block #{out['ledger_idx']} ({out['hash'][:12]})")
        except ValueError as e:
            st.error(str(e))
    prev = harness.decisions()
    prev = prev[prev.case_id == case_id]
    if len(prev):
        st.dataframe(prev[["ts", "user_id", "action", "recommended_action", "reason_code", "note", "ledger_idx"]],
                     hide_index=True, width="stretch")
st.caption(C.FOOTER)
