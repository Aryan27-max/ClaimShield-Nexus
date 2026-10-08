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
comms = g.groupby("community_id").agg(members=("community_size", "size"), comm_size=("community_size", "first"),
                                      density=("community_density", "first"))
one = len(comms) == 1
tiles = [("Community size", int(comms.comm_size.iloc[0]) if one else f"{len(comms)} communities",
          ", ".join(comms.index) + " (Louvain)"),
         ("Community density", f"{comms.density.iloc[0]:.2f}" if one else " / ".join(f"{d:.2f}" for d in comms.density),
          "share of possible links"),
         ("PPR percentile", f"{g.ppr_pct.max():.0%}", "proximity to confirmed fraud"),
         ("Reciprocal partners", int(g.reciprocal_partners.fillna(0).sum()), f"{int(g.cycles3.fillna(0).sum())} 3-way loops")]
for col, (label, value, delta) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, delta)
U.gap()

left, right = st.columns([3, 2])
with left, U.card("ego"):
    html, n = C.ego_html(entity, pids)
    U.html_line(U.legend({"provider": U.NODE_COLORS["provider"], "member": U.NODE_COLORS["member"],
                          "owner": U.NODE_COLORS["owner"], "address": U.NODE_COLORS["address"],
                          "bank": U.NODE_COLORS["bank"], "selected / ring member": U.NODE_COLORS["highlight"]}))
    st.caption(f"{n} nodes (cap 150) · bold red = referrals between these providers · pale red = other referrals · "
               "orange / green / purple = shared owner / address / bank")
    st.iframe(html, height=540)
with right:
    with U.card("shared"):
        st.subheader("Shared attributes")
        for col, n_col in [("owner_id", "shared_owner_n"), ("address_id", "shared_address_n"), ("bank_id", "shared_bank_n")]:
            for v, grp in p.groupby(col):
                outside = int(g.loc[grp.index, n_col].max()) - (len(grp) - 1)
                st.markdown(f"**{col.removesuffix('_id').capitalize()}** `{v}` · {len(grp)} of these providers"
                            + (f" + {outside} outside" if outside > 0 else ""))
    U.gap()
    with U.card("flows"):
        st.subheader("Referral flows")
        fl = C.referral_flows()
        for title, src, dst in [("Out (top 5)", "referring_provider_id", "provider_id"),
                                ("In (top 5)", "provider_id", "referring_provider_id")]:
            sub = fl[fl[src].isin(pids)]
            top = sub.groupby(dst).n.sum().sort_values(ascending=False)
            t = pd.DataFrame({"provider": top.index, "claims": top.values,
                              "share": (top / max(top.sum(), 1)).round(2).values}).head(5)
            t["in case"] = t.provider.isin(pids)
            st.markdown(f"**{title}**")
            st.dataframe(t, hide_index=True, width="stretch", column_config={
                "provider": st.column_config.TextColumn(width=75), "claims": st.column_config.NumberColumn(width=65),
                "share": st.column_config.ProgressColumn("share", min_value=0, max_value=1, width=115),
                "in case": st.column_config.CheckboxColumn(width=60)})

U.gap()
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
                 column_config={"$ at risk": st.column_config.NumberColumn(format="dollar", step=1)})
    cols = st.columns(len(rings) * 2 or 1)
    for i, rid in enumerate(rings):
        if cols[2 * i].button(f"Show {rid}", key=f"show_{rid}", width="stretch"):
            st.session_state["net_entity"] = rid
            st.rerun()
        if cols[2 * i + 1].button(f"Open case {rid}", key=f"open_{rid}", width="stretch"):
            st.session_state["case_id"] = rid
            st.switch_page("views/3_Case.py")
st.caption(C.FOOTER)
