"""Network: ego graph of a provider or ring, shared attributes, referral flows, community stats, all rings."""
import pandas as pd
import streamlit as st

from ui import common as C
from ui import style as U

gf = C.table("graph_features").assign(provider_id=lambda d: d.provider_id.astype(str))
prov = C.table("providers").astype({"provider_id": str, "owner_id": str, "address_id": str, "bank_id": str})
q = C.ranked()
rings = sorted(gf.ring_id.dropna().astype(str).unique())
options = rings + sorted(gf.provider_id)
cur = st.session_state.get("net_entity")
entity = st.selectbox("Provider or ring", options, index=options.index(cur) if cur in options else 0)
st.session_state["net_entity"] = entity
is_ring = entity in rings
pids = gf.provider_id[gf.ring_id == entity].tolist() if is_ring else [entity]
case = q[q.providers.map(lambda p: bool(set(p) & set(pids)))]

U.page_header("Network", f"{'Ring of ' + str(len(pids)) + ' providers' if is_ring else 'Provider'} {', '.join(pids)}"
                         + (f" · case {case.case_id.iloc[0]} · {case.recommended_action.iloc[0]}" if len(case) else
                            " · no case"))

g = gf.set_index("provider_id").loc[pids]
p = prov.set_index("provider_id").loc[pids]
tiles = [("Community size", int(g.community_size.max()), f"{g.community_id.iloc[0]} (Louvain)"),
         ("Community density", f"{g.community_density.max():.2f}", "share of possible links"),
         ("PPR percentile", f"{g.ppr_pct.max():.0%}", "proximity to confirmed fraud"),
         ("Reciprocal partners", int(g.reciprocal_partners.fillna(0).sum()), f"{int(g.cycles3.fillna(0).sum())} 3-way loops")]
for col, (label, value, delta) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, delta)
st.write("")

left, right = st.columns([3, 2])
with left, U.card("ego"):
    html, n = C.ego_html(entity, pids)
    U.html_line(U.legend({"provider": U.NODE_COLORS["provider"], "member": U.NODE_COLORS["member"],
                          "owner": U.NODE_COLORS["owner"], "address": U.NODE_COLORS["address"],
                          "bank": U.NODE_COLORS["bank"], "selected / ring member": U.NODE_COLORS["highlight"]}))
    st.caption(f"{n} nodes (cap 150) · red edges = referrals")
    st.iframe(html, height=540)
with right:
    with U.card("shared"):
        st.subheader("Shared attributes")
        rows = []
        for col, n_col in [("owner_id", "shared_owner_n"), ("address_id", "shared_address_n"), ("bank_id", "shared_bank_n")]:
            for v, grp in p.groupby(col):
                rows.append({"attribute": col.removesuffix("_id"), "value": v, "case providers": ", ".join(grp.index),
                             "other providers": int(g.loc[grp.index, n_col].max())})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.write("")
    with U.card("flows"):
        st.subheader("Referral flows")
        fl = C.referral_flows()
        for title, src, dst in [("Out (top 5)", "referring_provider_id", "provider_id"),
                                ("In (top 5)", "provider_id", "referring_provider_id")]:
            sub = fl[fl[src].isin(pids)]
            top = sub.groupby(dst).n.sum().sort_values(ascending=False)
            t = pd.DataFrame({"provider": top.index, "referred claims": top.values,
                              "share": (top / max(top.sum(), 1)).round(2).values}).head(5)
            t["in case"] = t.provider.isin(pids)
            st.markdown(f"**{title}**")
            st.dataframe(t, hide_index=True, width="stretch",
                         column_config={"share": st.column_config.ProgressColumn("share", min_value=0, max_value=1)})

st.write("")
with U.card("rings"):
    st.subheader("All detected rings")
    rr = []
    for rid in rings:
        mem = gf.provider_id[gf.ring_id == rid].tolist()
        cs = q[q.case_id == rid]
        rr.append({"ring": rid, "providers": ", ".join(mem), "size": len(mem),
                   "action": cs.recommended_action.iloc[0] if len(cs) else "—",
                   "$ at risk": float(cs.dollars_at_risk.iloc[0]) if len(cs) else 0.0})
    st.dataframe(U.table_style(pd.DataFrame(rr), "action"), hide_index=True, width="stretch",
                 column_config={"$ at risk": st.column_config.NumberColumn(format="dollar")})
    cols = st.columns(len(rings) * 2 or 1)
    for i, rid in enumerate(rings):
        if cols[2 * i].button(f"Show {rid}", key=f"show_{rid}", width="stretch"):
            st.session_state["net_entity"] = rid
            st.rerun()
        if cols[2 * i + 1].button(f"Open case {rid}", key=f"open_{rid}", width="stretch"):
            st.session_state["case_id"] = rid
            st.switch_page("pages/3_Case.py")
st.caption(C.FOOTER)
