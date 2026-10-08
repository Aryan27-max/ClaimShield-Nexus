"""Case view: evidence, risk forecast, timeline, ego network, limitations, rule trace, human decision form."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import brief, harness, identity, phi
from core import mandate as M
from ui import common as C
from ui import fmt
from ui import export as E
from ui import panels as P
from ui import style as U

q = C.ranked()
C.require_cases(q)
ids = q.case_id.tolist()
cur = st.session_state.get("case_id")
case_id = st.selectbox("Case", ids, index=ids.index(cur) if cur in ids else 0)
st.session_state["case_id"] = case_id
r = q.set_index("case_id").loc[case_id]
pol = C.policy()
seen = st.session_state.setdefault("viewed_cases", set())
if case_id not in seen:  # audit controls: who opened which case, once per case per session
    phi.log_case_view(C.me(), case_id)
    seen.add(case_id)

who = f"Ring of {r.n_providers} providers" if r.case_type == "ring" else "Provider"
U.page_header(f"Case {case_id}", f"{who} {', '.join(r.providers)} · {', '.join(r.provider_types)} · "
                                 f"rank #{r['rank']} · {r.status.replace('_', ' ')}")
U.html_line(U.action_badge(r.recommended_action), "&nbsp;", U.class_chips(r.classes))
U.gap()
tiles = [("Evidence confidence", fmt.pct(r.confidence), f"fused {fmt.pct(r.fused_score)} × completeness "
                                                        f"{fmt.pct(r.completeness)}"),
         (f"P(escalation, {q.attrs.get('horizon')} d)", f"{r.p_fwa:.0%}", "calibrated model" if r.has_model_score
          else "no model score"),
         ("$ at risk", fmt.money(r.dollars_at_risk), f"{r.n_flagged_claims:,} flagged claims"),
         ("Members affected", f"{r.members_affected:,}", f"{r.vulnerable_share:.0%} under 18 or 65+"),
         ("Est. hours", f"{r.est_hours:.0f}", "must-take" if r.must_take else "")]
for col, (label, value, delta) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, delta)
U.gap()
if r.recommended_action == "NEEDS_MORE_DATA":
    st.warning("Needs more data — missing evidence class(es): **" + ", ".join(r.missing_classes) +
               "**. Gather corroborating evidence before any escalation.")
if r.requires_human:
    st.info("REFER_TO_MFCU is allowed for this case and always requires a human decision.")

tab_ev, tab_risk, tab_tl, tab_net, tab_why, tab_comp, tab_brief = st.tabs(
    ["Evidence", "Risk forecast", "Timeline", "Network", "Why this action", "Compliance", "Brief"])
with tab_ev, U.card("evidence"):
    ev = pd.DataFrame(list(r.evidence))
    if len(ev):
        ev = ev.assign(value=ev.value.map(phi.mask_text), expected=ev.expected.map(phi.mask_text))
        st.dataframe(ev[["claim_id", "field", "value", "expected", "class", "code", "entity_id"]],
                     hide_index=True, width="stretch", height=360, column_config={
                         "claim_id": st.column_config.TextColumn(width=85), "field": st.column_config.TextColumn(width=125),
                         "value": st.column_config.TextColumn(width=190), "expected": st.column_config.TextColumn(width=285),
                         "class": st.column_config.TextColumn(width=80), "code": st.column_config.TextColumn(width=50),
                         "entity_id": st.column_config.TextColumn("entity", width=85)})
    d = st.columns(3)
    for col, (label, v) in zip(d, [("Deterministic $ (flagged claims)", r.dollars_deterministic),
                                   ("Structural $ (flagged claims)", r.dollars_structural),
                                   ("Statistical $ (excess vs peers)", r.dollars_statistical)]):
        with col:
            U.metric_tile(label, fmt.money(v))
    st.caption(f"{len(r.alert_ids)} alerts ({', '.join(r.codes)}). $ at risk = paid on the union of claim-level "
               "flags; statistical excess only counts when no claim-level evidence exists.")

with tab_ev, U.card("members"):
    P.members(r, case_id)

with tab_comp, U.card("compliance"):
    P.compliance(r, case_id, pol)

with tab_risk, U.card("risk"):
    if r.has_model_score:
        hs = [30, 60, 90]
        a, b = st.columns([3, 2])
        fig = go.Figure(go.Bar(x=[f"{h} days" for h in hs], y=[r[f"p_{h}"] for h in hs], marker_color=U.ACCENT,
                               text=[f"{r[f'p_{h}']:.0%}" for h in hs], textposition="outside", width=0.5))
        fig.update_layout(template=U.plotly_template(), height=300,
                          yaxis=dict(range=[0, 1.15], tickformat=".0%", title="P(escalation)"))
        U.plot(fig, a)
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
    fig = go.Figure([go.Bar(x=tl.index, y=tl[False], name="Paid (not flagged)", marker_color=U.pal()["accent-soft"]),
                     go.Bar(x=tl.index, y=tl[True], name="Paid (flagged)", marker_color=U.RED)])
    fig.update_layout(template=U.plotly_template(), barmode="stack", height=360, yaxis_title="Paid $ per month")
    U.plot(fig)

with tab_net, U.card("network"):
    if st.toggle("Show ego network (≤ 150 nodes)", value=False, key=f"net_{case_id}"):
        html, n = C.ego_html(case_id if r.case_type == "ring" else r.providers[0], list(r.providers))
        st.caption(f"{n} nodes · red = case providers; bold red edges = referrals between them · blue providers · "
                   "orange owners · green addresses · purple banks · grey members")
        st.iframe(html, height=540)

with tab_why, U.card("why"):
    st.subheader("Limitations")
    for lim in r.limitations:
        st.markdown(f"- {lim}")
    st.subheader("Why not a higher action")
    st.code("\n".join(r.rule_trace), language=None)
    st.caption(f"Policy v{r.policy_version} · {r.policy_hash[:16]} · allowed: {', '.join(r.allowed_actions)}")

with tab_brief, U.card("brief"):
    key = f"brief_{case_id}_{r.policy_hash[:12]}"
    st.caption("Deterministic template brief: every sentence is filled from case data. Generating it appends a "
               "`brief_generated` block with the brief's SHA-256 to the ledger.")
    if st.button("Generate brief", key="gen_brief", type="primary"):
        actor = f"human:{st.session_state['user_id']}" if st.session_state.get("user_id") else "system:brief"
        try:
            st.session_state[key] = brief.generate({**r.to_dict(), "case_id": case_id}, pol,
                                                   C.claims(C._mtime(C.S.OUT / "claims.parquet")),
                                                   C.table("providers"), C.table("graph_features"), C.meta(), actor=actor)
        except (OSError, ValueError, KeyError) as e:
            C.show_error(e, "Brief could not be generated")
    b = st.session_state.get(key)
    if b:
        a1, a2, a3 = st.columns([1, 1, 2])
        a1.download_button("Download .md", b["markdown"], file_name=f"brief_{case_id}.md", mime="text/markdown")
        a2.download_button("Download .html (print to PDF)", E.print_html(b["markdown"], f"Brief {case_id}"),
                           file_name=f"brief_{case_id}.html", mime="text/html")
        a3.caption(f"Ledger block #{b['ledger_idx']} · sha256 {b['sha256'][:16]} · {b['generated_at']}")
        st.markdown(b["markdown"])

U.gap()
with U.card("decision"):
    P.show_flash()
    P.authorisation(case_id, pol)
    st.subheader("Human decision")
    who, role = C.me(), C.my_role()
    can_sign = role in ("investigator", "siu_lead")
    st.caption(f"Signing as {who} ({identity.ROLE_LABELS.get(role, role)}) · the Ed25519 decision mandate binds the "
               "case, evidence and policy hashes")
    with st.form("decision", clear_on_submit=False, border=False):
        a, b = st.columns(2)
        action = a.selectbox("Action (allowed by policy)", list(r.allowed_actions), key="action")
        reasons = pol["reason_codes"]
        reason = b.selectbox("Reason code", list(reasons), format_func=lambda k: f"{k} — {reasons[k]}", key="reason_code")
        note = a.text_area("Note", key="note", height=68)
        amount = b.number_input("Overpayment amount $ (OVERPAYMENT_IDENTIFIED only)", min_value=0.0, value=0.0,
                                step=100.0, key="amount")
        submitted = st.form_submit_button("Sign & submit", type="primary", disabled=not can_sign)
    if not can_sign:
        st.info("Auditors have read-only access and cannot sign decisions.")
    if submitted:
        amt = float(amount) if reason == "OVERPAYMENT_IDENTIFIED" else None
        try:
            block = M.sign_decision({**r.to_dict(), "case_id": case_id}, pol, action, reason, note, who, amt)
            out = harness.decide(case_id, action, who, reason, note, cases=q, policy=pol, mandate=block, amount=amt)
            state = ("pending approval: a different SIU lead must add the second signature"
                     if out["status"] == "PENDING_APPROVAL" else "executed")
            st.success(f"Signed {action} on {case_id} ({state}) → ledger block #{out['ledger_idx']} · mandate "
                       f"{out['mandate_hash'][:12]}")
        except ValueError as e:
            st.error(str(e))
    prev = harness.decisions()
    prev = prev[prev.case_id == case_id]
    if len(prev):
        st.dataframe(prev[["ts", "user_id", "action", "status", "reason_code", "note", "ledger_idx"]],
                     hide_index=True, width="stretch")
st.caption(C.FOOTER)
