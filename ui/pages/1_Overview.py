"""Overview: alert-collapse funnel, $ at risk, capacity, synthetic validation, fairness check, model vs baseline."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from eval import metrics as M
from ui import common as C
from ui import style as U

q, m = C.ranked(), C.meta()
f = m.get("funnel", {})
n_claims = len(C.claims(C._mtime(C.S.OUT / "claims.parquet")))
n_queued = int((q.status != "not_queued").sum())
n_slate = int((q.status == "in_capacity").sum())
reduction = 1 - n_queued / max(f.get("claims_flagged", 1), 1)

U.page_header("Overview", f"Synthetic Medicaid program · data through {m.get('asof', '—')} · "
                          f"{st.session_state.get('investigators')} investigators · policy {q.policy_hash.iloc[0][:10]}")

steps = [("Claims", n_claims, "all claim lines"), ("Flagged claims", f.get("claims_flagged", 0), "rule / lens hits"),
         ("Alerts", f.get("alerts", 0), "entity-level"), ("Cases", len(q), "provider or ring"),
         ("Need investigator time", n_queued, "excl. monitor / needs data"), ("This week's slate", n_slate, "in capacity")]
for col, (label, value, delta) in zip(st.columns(len(steps)), steps):
    with col:
        U.metric_tile(label, f"{value:,}", delta, "green" if label == "This week's slate" else None)
st.write("")

a, b = st.columns([3, 2])
with a, U.card("funnel"):
    st.subheader(f"{reduction:.1%} alert reduction")
    st.caption(f"{f.get('claims_flagged', 0):,} flagged claims collapse into {n_queued} cases that need an "
               f"investigator, and {n_slate} fit this week's capacity. Log scale.")
    fig = go.Figure(go.Bar(y=[s[0] for s in steps][::-1], x=[s[1] for s in steps][::-1], orientation="h",
                           marker_color=[U.GREEN] + [U.ACCENT] * (len(steps) - 1),
                           text=[f"{s[1]:,}" for s in steps][::-1], textposition="outside"))
    fig.update_layout(template=U.plotly_template(), height=320, xaxis=dict(type="log", showticklabels=False),
                      yaxis=dict(showgrid=False))
    st.plotly_chart(fig, width="stretch")
with b, U.card("dollars"):
    st.subheader("$ at risk by recommended action")
    d = q.groupby("recommended_action").dollars_at_risk.sum().reindex(list(U.ACTION_COLORS)[::-1]).dropna()
    fig = go.Figure(go.Bar(x=[x.replace("_", " ").title() for x in d.index], y=d.values,
                           marker_color=[U.ACTION_COLORS[x] for x in d.index],
                           text=[f"${v / 1e3:,.0f}k" for v in d.values], textposition="outside"))
    fig.update_layout(template=U.plotly_template(), height=250, yaxis=dict(title="$", showticklabels=False))
    st.plotly_chart(fig, width="stretch")
    U.metric_tile("Weeks to clear the queue", q.attrs.get("weeks_to_clear"),
                  f"{q.attrs.get('queued_hours', 0):.0f} queued h ÷ {q.attrs.get('capacity_hours', 0):.0f} h/week")

st.write("")
st.header("Synthetic validation")
st.caption("Ground truth exists only because the data is synthetic. Only this evaluation reads it; the detection "
           "lenses, fusion and harness never do.")
lab = C.labels()
c1, c2 = st.columns([3, 2])
with c1, U.card("recall"):
    st.subheader("Recall per planted scheme")
    rc = M.recall(q, lab)
    fig = go.Figure([go.Bar(x=rc.scheme, y=rc.any_case, name="Any case", marker_color=U.ACCENT_SOFT),
                     go.Bar(x=rc.scheme, y=rc.prepay_plus, name="Prepay review or higher", marker_color=U.ACCENT)])
    fig.update_layout(template=U.plotly_template(), barmode="group", height=320, yaxis=dict(tickformat=".0%"))
    st.plotly_chart(fig, width="stretch")
with c2, U.card("legit"):
    st.subheader("Legitimate outliers")
    st.caption("High-cost oncology, busy ERs and honest one-off billing slips: none may reach FULL or MFCU.")
    st.dataframe(M.legit_outcomes(q, lab), width="stretch")
    v = M.validation(q, lab)
    U.metric_tile("Clean providers escalated", v["clean_escalated"], "any action needing investigator time",
                  "green" if v["clean_escalated"] == 0 else "red")

st.write("")
c3, c4 = st.columns(2)
with c3, U.card("fairness"):
    st.subheader("Fairness check: flag rate by provider type")
    fr = M.flag_rates(q, "type", lab)
    fig = go.Figure([go.Bar(x=fr.type, y=fr.flag_rate, name="All providers", marker_color=U.ACCENT),
                     go.Bar(x=fr.type, y=fr.clean_rate, name="Clean providers (false positives)", marker_color=U.ORANGE)])
    fig.add_hline(y=fr.attrs["overall"], line_dash="dot", line_color=U.GRAY,
                  annotation_text=f"overall {fr.attrs['overall']:.1%}")
    fig.update_layout(template=U.plotly_template(), barmode="group", height=300, yaxis=dict(tickformat=".0%"))
    st.plotly_chart(fig, width="stretch")
    with st.expander("By specialty"):
        st.dataframe(M.flag_rates(q, "specialty", lab), hide_index=True, width="stretch")
    st.caption("Peer groups are specialty + type, so a specialty is never compared with another. Higher rates "
               "where schemes were planted (DME, home health) are expected; the clean-provider rate is the "
               "fairness signal and should stay near zero in every group.")
with c4, U.card("model"):
    st.subheader("Forecast model vs naive baseline")
    mb = pd.DataFrame(m.get("model_comparison", []))
    if mb.empty:
        st.info("No model metrics yet: run `python -m core.pipeline`.")
    else:
        piv = mb.pivot(index="h", columns="scorer", values="roc_auc")
        npos = mb[mb.scorer == "model new-onset"].set_index("h").n_pos
        tbl = piv.assign(**{"new-onset positives": npos})[
            ["model", "baseline", "model new-onset", "baseline new-onset", "new-onset positives"]]
        st.dataframe(tbl.rename_axis("horizon (days)"), width="stretch")
        pr = mb.pivot(index="h", columns="scorer", values="pr_auc")
        st.caption(f"ROC-AUC on the embargoed test split (T ≥ 2025-01). Baseline = strong flag in the last 90 days. "
                   f"PR-AUC model / baseline: " + " · ".join(f"{h} d {pr.loc[h, 'model']:.2f} / {pr.loc[h, 'baseline']:.2f}"
                                                             for h in pr.index) + ".")
        st.markdown("**Honest read:** on already-flagged providers the persistence baseline is as good or better. "
                    "The model's value is early warning for providers **without** flag history (new-onset), where the "
                    "baseline is blind (AUC 0.5); those results rest on few positives. A forecast is never evidence.")
st.caption(C.FOOTER)
