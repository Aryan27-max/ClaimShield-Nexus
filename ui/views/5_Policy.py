"""Policy: the human defines the rules. Edit thresholds, preview impact in memory, save as a new hashed version."""
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import harness
from core import mandate as MD
from core import policy_edit as PE
from eval import metrics as M
from ui import common as C
from ui import fmt
from ui import glossary as G
from ui import style as U

pol, cases = C.policy(), C.cases()
U.page_header("Policy", "Change a threshold, preview who would be affected, then sign a new version (SIU lead only). "
                        "Models propose, this policy constrains, a human decides.")
if msg := st.session_state.pop("policy_saved", None):
    U.result_card(True, msg)
    st.toast("New policy version signed and saved", icon=":material/gavel:")
    U.gap()

created = fmt.day(pol.get("created") or datetime.fromtimestamp(Path(pol["_path"]).stat().st_mtime))
tiles = [("Active version", f"v{pol['version']}", Path(pol["_path"]).name), ("Policy hash", pol["_hash"][:10], "sha256 of YAML"),
         ("Author", pol.get("author", "—"), pol.get("change_reason", "initial policy")[:40]), ("Created", created, "")]
for col, (label, value, delta) in zip(st.columns(len(tiles)), tiles):
    with col:
        U.metric_tile(label, value, delta, small=label == "Author")
U.gap()

with U.card("authorisation"):
    ok, why, pm = MD.policy_status(pol)
    st.subheader("Authorisation (intent mandate)")
    U.html_line(U.chip("authorised" if ok else "not authorised", "green" if ok else "red"), why)
    st.caption(f"Dual control: {', '.join(map(U.action_label, pol.get('dual_control_actions', []))) or 'none'} · automation may only route "
               f"{', '.join(map(U.action_label, pol.get('automation_scope', []))) or 'nothing'} · program {pol.get('program', '—')} · record "
               f"retention {pol.get('record_retention_years', '—')} years (display only)")
    if ok and C.my_role() == "siu_lead":
        with st.expander("Revoke this policy version"):
            reason = st.text_input("Revocation reason", key="policy_revoke_reason")
            if st.button("Revoke policy version", key="danger_policy_revoke"):
                try:
                    MD.revoke(pm["mandate_hash"], reason, C.me())
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
U.gap()

values, avail = {}, PE.available_thresholds(pol)
with U.card("thresholds"):
    st.subheader("Key thresholds")
    st.caption("Hover the ? next to a threshold to see what it controls. Nothing changes until you preview and save.")
    cols = st.columns(3)
    for i, (path, label) in enumerate(avail.items()):
        v, key = PE.get_threshold(pol, path), f"th_{path}_{pol['_hash'][:8]}"
        label = G.THRESHOLD_LABELS.get(path, label)
        with cols[i % 3]:
            if isinstance(v, float) and v <= 1:
                values[path] = st.slider(label, 0.0, 1.0, float(v), 0.01, key=key, help=G.THRESHOLD_HELP.get(path))
            elif path.startswith("capacity."):
                values[path] = st.number_input(label, min_value=1, max_value=168, value=int(v), step=1, key=key,
                                               help=G.THRESHOLD_HELP.get(path))
            else:
                values[path] = st.number_input(label, min_value=0, value=int(v), step=1000 if v > 1000 else 1, key=key,
                                               help=G.THRESHOLD_HELP.get(path))
    if missing := [label for path, label in PE.THRESHOLDS.items() if path not in avail]:
        st.caption("Not in this policy version: " + ", ".join(missing))
    changed = {k: v for k, v in values.items() if v != PE.get_threshold(pol, k)}
    st.caption("Changed: " + (", ".join(f"{PE.THRESHOLDS[k]} {PE.get_threshold(pol, k)} → {v}"
                                        for k, v in changed.items()) or "nothing yet"))
try:
    new = PE.with_thresholds(pol, changed)
except ValueError as e:
    new, changed = None, {}
    st.error(f"These values are not a valid policy: {e}")

U.gap()
if st.button("Preview impact", key="preview", type="primary", disabled=not changed):
    st.session_state["preview_of"] = changed
    st.toast("Preview computed in memory; nothing saved", icon=":material/visibility:")
if not changed:
    st.caption("Change a threshold above to enable the preview.")
if st.session_state.get("preview_of") == changed and changed:
    after = harness.evaluate_all(cases.drop(columns=harness.OUTPUT_COLS), new)
    d = PE.diff(cases, pol, new)
    counts = pd.DataFrame({"before": cases.recommended_action.value_counts(),
                           "after": after.recommended_action.value_counts()}).reindex(harness.ACTIONS[::-1]).fillna(0).astype(int)
    counts["change"] = counts.after - counts.before
    a, b = st.columns([2, 3])
    with a, U.card("counts"):
        st.subheader("Action counts")
        fig = go.Figure([go.Bar(x=counts.index.str.replace("_", " ").str.title(), y=counts.before, name="Before",
                                marker_color=U.pal()["accent-soft"]),
                         go.Bar(x=counts.index.str.replace("_", " ").str.title(), y=counts.after, name="After",
                                marker_color=U.ACCENT)])
        fig.update_layout(template=U.plotly_template(), barmode="group", height=280)
        U.plot(fig)
        st.dataframe(counts, width="stretch")
    with b, U.card("changes"):
        st.subheader(f"{len(d)} case(s) change action")
        st.dataframe(U.table_style(d, "after"), hide_index=True, width="stretch", height=300)
    U.gap()
    with U.card("validation"):
        if not C.has_ground_truth():
            st.info("No ground truth available: validation deltas need labelled outcomes.")
        else:
            st.subheader("Synthetic validation deltas")
            st.caption("Ground truth exists only because the data is synthetic.")
            vb, va = M.validation(cases, C.labels()), M.validation(after, C.labels())
            rows = [("Upcoding providers at PREPAY+", "upcoding_prepay_plus", True),
                    ("Planted entities at PREPAY+", "planted_prepay_plus", True),
                    ("Clean providers escalated", "clean_escalated", False),
                    ("Legit outliers at FULL / MFCU", "legit_full_or_mfcu", False)]
            for col, (label, k, up_good) in zip(st.columns(len(rows)), rows):
                delta = va[k] - vb[k]
                tone = None if delta == 0 else ("green" if (delta > 0) == up_good else "red")
                with col:
                    U.metric_tile(label, f"{vb[k]} → {va[k]}", f"{delta:+d}", tone)

U.gap()
with U.card("save"):
    st.subheader("Save as new version")
    st.caption("Writes policy/harness_vN.yaml (older versions are never overwritten) and appends a policy_change "
               "block (old hash → new hash, author, reason) to the ledger. The queue re-ranks under the new version.")
    author, is_lead = C.me(), C.my_role() == "siu_lead"
    st.caption(f"Signing as {author}: " + ("the new version is signed with your key (policy mandate)." if is_lead else
                                          "only an SIU lead can sign a new policy version."))
    with st.form("save_policy", border=False):
        reason = st.text_input("Change reason", key="policy_reason")
        save = st.form_submit_button("Sign & save as new version", type="primary", disabled=not (changed and is_lead))
    if save:
        try:
            out = PE.save_version(new, author, reason, old=pol)
            st.session_state["pending_policy"] = out["path"]
            st.session_state["policy_saved"] = (f"Saved v{out['version']} · {out['hash'][:10]} → ledger block "
                                                f"#{out['ledger_idx']}. Queue now ranks under this version.")
            st.session_state.pop("preview_of", None)
            st.rerun()
        except (ValueError, OSError) as e:
            st.error(f"Not saved: {e}")
st.caption(C.FOOTER)
