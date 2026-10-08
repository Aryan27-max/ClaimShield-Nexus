"""Case view: evidence, timeline, ego network, limitations, rule trace, human decision form."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import harness
from ui import common as C

q = C.ranked()
ids = q.case_id.tolist()
cur = st.session_state.get("case_id")
case_id = st.selectbox("Case", ids, index=ids.index(cur) if cur in ids else 0)
st.session_state["case_id"] = case_id
r = q.set_index("case_id").loc[case_id]
pol = C.policy()

st.title(f"Case {case_id}")
st.markdown(f"{'Ring of ' + str(r.n_providers) + ' providers' if r.case_type == 'ring' else 'Provider'}: "
            f"**{', '.join(r.providers)}** ({', '.join(r.provider_types)}) · rank #{r['rank']} · {r.status}")
m = st.columns(5)
m[0].metric("Recommended action", r.recommended_action.replace("_", " ").title())
m[1].metric("Confidence", f"{r.confidence:.2f}", help=f"fused {r.fused_score:.2f} × completeness {r.completeness:.2f}")
m[2].metric("$ at risk", f"${r.dollars_at_risk:,.0f}")
m[3].metric("Members affected", f"{r.members_affected:,}", help=f"{r.vulnerable_share:.0%} under 18 or 65+")
m[4].metric("Est. hours", f"{r.est_hours:.0f}")
st.markdown("Evidence classes: " + C.chips(r.classes) + "  ·  scores: " +
            ", ".join(f"{c} {r[f'score_{c}']:.2f}" for c in r.classes))
if r.recommended_action == "NEEDS_MORE_DATA":
    st.warning("Needs more data — missing evidence class(es): **" + ", ".join(r.missing_classes) +
               "**. Gather corroborating evidence before any escalation.")
if r.requires_human:
    st.info("REFER_TO_MFCU is allowed for this case and always requires a human decision.")

tab_ev, tab_risk, tab_tl, tab_net, tab_why = st.tabs(["Evidence", "Risk forecast", "Timeline", "Network",
                                                     "Why this action"])

with tab_risk:
    if r.has_model_score:
        hs = [30, 60, 90]
        fig = go.Figure(go.Bar(x=[f"{h} days" for h in hs], y=[r[f"p_{h}"] for h in hs], marker_color="#0071E3",
                               text=[f"{r[f'p_{h}']:.0%}" for h in hs], textposition="outside"))
        fig.update_layout(height=280, yaxis=dict(range=[0, 1.1], tickformat=".0%", title="P(escalation)"),
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.markdown(f"**Top drivers** (provider {r.driver_provider}, latest snapshot):")
        for d in r.drivers:
            st.markdown(f"- {d['label'].capitalize()}: **{d['value']}**")
        st.caption("Calibrated LightGBM forecast of a strong alert or confirmed investigation within the horizon. "
                   "A forecast is not evidence: it never counts toward FULL_INVESTIGATION or MFCU.")
    else:
        st.info("No model score for this provider; the queue uses fused confidence.")

with tab_ev:
    ev = pd.DataFrame(list(r.evidence))
    if len(ev):
        st.dataframe(ev[["claim_id", "field", "value", "expected", "lens", "class", "code", "entity_id"]],
                     hide_index=True, width="stretch", height=360)
    d = st.columns(3)
    d[0].metric("Deterministic $ (flagged claims)", f"${r.dollars_deterministic:,.0f}")
    d[1].metric("Structural $ (flagged claims)", f"${r.dollars_structural:,.0f}")
    d[2].metric("Statistical $ (excess vs peers)", f"${r.dollars_statistical:,.0f}")
    st.caption(f"{r.n_flagged_claims:,} flagged claims across {len(r.alert_ids)} alerts ({', '.join(r.codes)}). "
               "$ at risk = paid on the union of claim-level flags; statistical excess only counts when no claim-level evidence exists.")

with tab_tl:
    c = C.claims(C._mtime(C.S.OUT / "claims.parquet"))
    c = c[c.provider_id.isin(list(r.providers))]
    flagged = set(r.flagged_claim_ids)
    c = c.assign(month=c.service_date.dt.to_period("M").dt.to_timestamp(), flagged=c.claim_id.isin(flagged))
    tl = c.groupby(["month", "flagged"]).paid_amt.sum().unstack(fill_value=0).reindex(columns=[False, True], fill_value=0)
    fig = go.Figure([go.Bar(x=tl.index, y=tl[False], name="Paid (not flagged)", marker_color="#9ecae1"),
                     go.Bar(x=tl.index, y=tl[True], name="Paid (flagged)", marker_color="#E45756")])
    fig.update_layout(barmode="stack", height=360, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="Paid $ per month", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, width="stretch")

with tab_net:
    if st.toggle("Show ego network (≤ 150 nodes)", value=False, key=f"net_{case_id}"):
        html, n = C.ego_html(case_id if r.case_type == "ring" else r.providers[0], list(r.providers))
        st.caption(f"{n} nodes · red = case providers / referral edges · blue providers · orange owners · "
                   "green addresses · purple banks · grey members")
        st.iframe(html, height=540)

with tab_why:
    st.subheader("Limitations")
    for lim in r.limitations:
        st.markdown(f"- {lim}")
    st.subheader("Why not a higher action")
    st.code("\n".join(r.rule_trace), language=None)
    st.caption(f"Policy v{r.policy_version} · {r.policy_hash[:16]} · allowed: {', '.join(r.allowed_actions)}")

st.divider()
st.subheader("Human decision")
with st.form("decision", clear_on_submit=False):
    a, b = st.columns(2)
    user_id = a.text_input("Investigator user_id", key="user_id")
    action = b.selectbox("Action (allowed by policy)", list(r.allowed_actions), key="action")
    reasons = pol["reason_codes"]
    reason = a.selectbox("Reason code", list(reasons), format_func=lambda k: f"{k} — {reasons[k]}", key="reason_code")
    note = b.text_area("Note", key="note", height=68)
    submitted = st.form_submit_button("Record decision", type="primary")
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
