"""Deterministic investigation brief (markdown). No LLM: every sentence is a template filled from case data.
generate() appends a `brief_generated` ledger block holding the brief's sha256."""
import hashlib

import pandas as pd

from core import ledger, mandate, phi
from core.policy_schema import regulatory_basis

MAX_ROWS = 8
CLASS_ORDER = ["deterministic", "structural", "statistical"]
FOOTER = "Recommendation only. Final action requires an authorised human decision."
REQUESTS = {
    "deterministic": "Medical records sample: request records for up to 20 flagged claims to test billed level, "
                     "units and medical necessity against documentation.",
    "structural": "Ownership documents: request ownership / managing-employee disclosures and the payment bank "
                  "account to confirm or rule out shared control with other providers.",
    "statistical": "Peer comparison: re-run the peer-group analysis on the next quarter of claims.",
}
SOURCES = [
    ("claims", "claim_id, provider_id, member_id, service_date, paid_amt"),
    ("providers", "provider_id, type, specialty, owner_id, address_id, bank_id"),
    ("alerts (rules · anomaly · graph)", "alert_id, code, severity, score, claim_ids, evidence"),
    ("graph_features", "ring_id, shared_*_n, out/in_top1(_share), reciprocal_partners, cycles3, "
                       "community_size, community_density, ppr_pct"),
    ("predictions", "p_fwa (h = 30/60/90), SHAP drivers"),
]


def _cell(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def _table(rows: list[list], head: list[str]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return out + ["| " + " | ".join(_cell(x) for x in r) + " |" for r in rows]


def _usd(v) -> str:
    return f"${float(v):,.0f}"


def _who(case) -> str:
    return f"Ring of {case['n_providers']} providers" if case["case_type"] == "ring" else "Provider"


def header(case, policy: dict, generated_at: str, ledger_idx) -> list[str]:
    rows = [["Case", case["case_id"]], ["Providers", ", ".join(case["providers"])],
            ["Recommended action", case["recommended_action"]], ["Evidence confidence", f"{case['confidence']:.2f}"],
            ["$ at risk", _usd(case["dollars_at_risk"])], ["Members affected", f"{case['members_affected']:,}"],
            ["Policy", f"v{policy['version']} · {policy['_hash'][:12]}"], ["Generated", generated_at],
            ["Ledger block", f"#{ledger_idx} (brief_generated)"]]
    return _table(rows, ["Field", "Value"])


def summary(case) -> list[str]:
    cls = ", ".join(case["classes"])
    s = [f"{_who(case)} {', '.join(case['providers'])} is recommended for {case['recommended_action']} with evidence "
         f"confidence {case['confidence']:.2f} from {case['n_classes']} evidence class(es): {cls}.",
         f"{case['n_flagged_claims']:,} flagged claims carry {_usd(case['dollars_at_risk'])} at risk across "
         f"{case['members_affected']:,} members ({case['vulnerable_share']:.0%} under 18 or 65+)."]
    if "rank" in case:
        s.append(f"It ranks #{case['rank']} in the queue: priority {case['priority']:,.0f} = P(escalation) "
                 f"{case['p_fwa']:.2f} × $ at risk × severity weight {case['severity_w']:.1f} × member-harm weight "
                 f"{case['member_harm_w']:.2f} ÷ {case['est_hours']:.0f} est. hours; status {case['status']}.")
    return [" ".join(s)]


def evidence(case) -> list[str]:
    ev = pd.DataFrame(list(case["evidence"]))
    out = []
    for c in CLASS_ORDER:
        sub = ev[ev["class"] == c] if len(ev) else ev
        out.append(f"### {c.capitalize()}")
        if not len(sub):
            out += ["No evidence in this class.", ""]
            continue
        rows = [[r.claim_id or "—", r.field, phi.mask_text(r.value), phi.mask_text(r.expected), r.code]
                for r in sub.head(MAX_ROWS).itertuples()]
        out += _table(rows, ["claim_id", "field", "value", "expected", "code"])
        if len(sub) > MAX_ROWS:
            out.append(f"\n{len(sub) - MAX_ROWS} more in case file.")
        out.append("")
    out.append(f"Alerts: {', '.join(case['alert_ids'])}. Full list of {case['n_flagged_claims']:,} flagged "
               "claim ids in case file.")
    return out


def timeline(case, claims: pd.DataFrame) -> list[str]:
    c = claims[claims.provider_id.astype(str).isin(list(case["providers"]))]
    c = c.assign(month=c.service_date.dt.to_period("M").astype(str),
                 flagged=c.claim_id.astype(str).isin(set(case["flagged_claim_ids"])))
    c = c.assign(fpaid=c.paid_amt.where(c.flagged, 0.0))
    g = c.groupby("month").agg(n=("claim_id", "size"), paid=("paid_amt", "sum"), nf=("flagged", "sum"),
                               fpaid=("fpaid", "sum"))
    rows = [[m, f"{r.n:,}", _usd(r.paid), f"{int(r.nf):,}", _usd(r.fpaid)] for m, r in g.iterrows()]
    return _table(rows, ["month", "claims", "paid", "flagged claims", "flagged paid"])


def network(case, providers: pd.DataFrame, gf: pd.DataFrame) -> list[str]:
    pids = list(case["providers"])
    p = providers.astype(str).set_index("provider_id")
    g = gf.assign(provider_id=gf.provider_id.astype(str)).set_index("provider_id")
    out = []
    if case["case_type"] == "ring":
        comms = g.loc[pids].groupby("community_id").agg(members=("community_size", "size"),
                                                         comm_size=("community_size", "first"),
                                                         density=("community_density", "first"))
        out.append(f"Ring {case['case_id']}: {len(pids)} providers; Louvain communities: " + "; ".join(
            f"{cid} (size {int(r['comm_size'])}, density {r['density']:.2f}) holds {int(r['members'])} of them"
            for cid, r in comms.iterrows()) + ".")
    rows = []
    for pid in pids:
        pr, r = p.loc[pid], g.loc[pid]
        rows.append([pid, pr["type"], f"{pr.owner_id} ({int(r.shared_owner_n)})", f"{pr.address_id} ({int(r.shared_address_n)})",
                     f"{pr.bank_id} ({int(r.shared_bank_n)})",
                     f"{r.out_top1} {r.out_top1_share:.0%}" if pd.notna(r.out_top1) else "—",
                     f"{r.in_top1} {r.in_top1_share:.0%}" if pd.notna(r.in_top1) else "—",
                     f"{int(r.reciprocal_partners)} / {int(r.cycles3)}", f"{r.ppr_pct:.0%}"])
    out += _table(rows, ["provider", "type", "owner (other providers)", "address (others)", "bank (others)",
                         "top referral out", "top referral in", "reciprocal / 3-loops", "PPR pct"])
    loops = [e["value"] for e in case["evidence"] if e["field"] in ("referral_cycle", "reciprocal_referral")]
    if loops:
        out += ["", "Referral loops: " + "; ".join(loops[:6]) + ("." if len(loops) <= 6 else f"; {len(loops) - 6} more.")]
    return out


def forecast(case, meta: dict) -> list[str]:
    if not case.get("has_model_score", False):
        return ["No model score for this provider (no snapshot); the queue uses evidence confidence."]
    out = _table([[f"{h} days", f"{case[f'p_{h}']:.2f}"] for h in (30, 60, 90)], ["horizon", "P(escalation)"])
    out += ["", f"Top drivers (provider {case['driver_provider']}):"]
    out += [f"{i}. {d['label'].capitalize()} = {d['value']}" for i, d in enumerate(case["drivers"], 1)]
    mt = meta.get("model_test", {}).get("90", {})
    out += ["", f"Model quality: test ROC-AUC {mt.get('roc_auc', '—')} at 90 days (T ≥ 2025-01, embargoed split). "
            "The forecast is an early warning for providers without flag history (new-onset); on already-flagged "
            "providers a naive persistence baseline is as good or better. A forecast is not evidence."]
    return out


def confidence(case) -> list[str]:
    sc = ", ".join(f"{c} {case[f'score_{c}']:.2f}" for c in CLASS_ORDER if c in case["classes"])
    out = [f"Confidence {case['confidence']:.2f} = fused score {case['fused_score']:.2f} (weighted noisy-OR of "
           f"class scores: {sc}) × data completeness {case['completeness']:.2f}.", ""]
    return out + [f"- {x}" for x in case["limitations"]] if len(case["limitations"]) else out + ["- None recorded."]


def checklist(case) -> list[str]:
    if case["recommended_action"] != "NEEDS_MORE_DATA":
        return [f"Not applicable: recommended action is {case['recommended_action']}."]
    out = [f"- [ ] {REQUESTS[c]}" for c in case["missing_classes"] if c in REQUESTS]
    out.append(f"- [ ] Member verification calls: confirm services with {min(10, int(case['members_affected']))} "
               "sampled members.")
    if case["completeness"] < 1:
        out.append("- [ ] More history: wait for 90 days / 30 claims of activity or request prior-payer history.")
    return out


def action(case) -> list[str]:
    out = [f"Recommended: **{case['recommended_action']}**. Allowed by policy: {', '.join(case['allowed_actions'])}."]
    if case["requires_human"]:
        out.append("REFER_TO_MFCU is allowed and always requires a human decision.")
    return out + ["The deciding investigator signs the decision (Ed25519 decision mandate bound to case, evidence and "
                  "policy hashes); dual-control actions execute only after a second SIU-lead signature."]


def basis(case, policy: dict) -> list[str]:
    rows = regulatory_basis(policy, case["recommended_action"], case["codes"])
    out = [f"- **{t}**: {c}" for t, c in rows] or [f"No citation recorded for {case['recommended_action']} (routing)."]
    hipaa = policy.get("regulatory_basis", {}).get("hipaa", "45 CFR 164.502(b)")
    return out + ["", f"Member identifiers in this brief are masked (minimum necessary: {hipaa}).",
                  "Citations are for orientation, not legal advice; state rules vary."]


def authorisation(chain: list[dict] | None) -> list[str]:
    if not chain:
        return ["No signed decision for this case yet."]
    rows = []
    for c in chain:
        b = c["block"] or {}
        who = b.get("approver") or b.get("signer") or b.get("issuer") or "—"
        rows.append([c["step"], who, b.get("fingerprint", "—"), str(b.get("mandate_hash") or "—")[:12],
                     "✓" if c["signature_ok"] else "✕", "✓" if c["links_ok"] else "✕"])
    return _table(rows, ["step", "signer", "key fingerprint", "mandate", "signature", "links"])


def build(case, policy: dict, claims: pd.DataFrame, providers: pd.DataFrame, gf: pd.DataFrame, meta: dict,
          generated_at: str, ledger_idx, chain: list[dict] | None = None) -> str:
    """Pure: same inputs => byte-identical markdown."""
    case = dict(case)
    sections = [("Header", header(case, policy, generated_at, ledger_idx)), ("Summary", summary(case)),
                ("Evidence by class", evidence(case)), ("Timeline", timeline(case, claims)),
                ("Network context", network(case, providers, gf)), ("Forecast", forecast(case, meta)),
                ("Confidence & limitations", confidence(case)),
                ("Why not a higher action", ["```"] + list(case["rule_trace"]) + ["```"]),
                ("Evidence that would change this", checklist(case)),
                ("Recommended human action", action(case)), ("Regulatory basis", basis(case, policy)),
                ("Authorisation chain", authorisation(chain)),
                ("Data sources", [f"- **{t}**: {f}" for t, f in SOURCES] +
                 [f"- **policy**: {policy['_path'].rsplit('/', 1)[-1]} (sha256 {policy['_hash'][:16]})"]),
                ("Decision notice", [f"**{FOOTER}**"])]
    lines = [f"# Investigation brief — {case['case_id']}", ""]
    for i, (title, body) in enumerate(sections, 1):
        lines += [f"## {i}. {title}", "", *body, ""]
    return "\n".join(lines)


def generate(case, policy: dict, claims: pd.DataFrame, providers: pd.DataFrame, gf: pd.DataFrame, meta: dict,
             actor: str = "system:brief", db=None, now: str | None = None) -> dict:
    """Builds the brief inside the ledger write, so the block it cites is exactly the `brief_generated` block
    holding its sha256 (no race with concurrent appends)."""
    now = now or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    out, chain = {}, mandate.verify_chain(case["case_id"], db)

    def payload(idx: int) -> dict:
        out["markdown"] = build(case, policy, claims, providers, gf, meta, now, idx, chain)
        out["sha256"] = hashlib.sha256(out["markdown"].encode()).hexdigest()
        return {"case_id": case["case_id"], "brief_sha256": out["sha256"], "policy_version": policy["version"],
                "policy_hash": policy["_hash"], "generated_at": now}

    entry = ledger.append(actor, "brief_generated", payload, db)
    return {**out, "ledger_idx": entry["idx"], "generated_at": now}
