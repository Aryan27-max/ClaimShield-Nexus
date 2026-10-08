"""Plain-language definitions for the domain terms the UI uses (content, not styling)."""
import streamlit as st

TERMS = {
    "MFCU": "Medicaid Fraud Control Unit: the state unit that prosecutes provider fraud. A referral to the MFCU is the "
            "most serious action here and always needs two signatures.",
    "Credible allegation of fraud": "An allegation with indicia of reliability. Under 42 CFR 455.23 it triggers a "
                                    "payment-suspension determination and a written MFCU referral.",
    "Prepay review": "Claims from the provider are checked before payment instead of after.",
    "Needs more data": "The evidence is not strong enough to act on. The system abstains instead of escalating and "
                       "lists what would change its mind.",
    "Evidence class": "Where a signal comes from: deterministic (billing rules), structural (the network graph) or "
                      "statistical (peer comparison). Independent classes corroborate each other; the forecast is "
                      "never a class.",
    "Confidence": "How strongly the evidence supports the case: the classes' scores combined, times a data "
                  "completeness factor. It is not a probability of guilt.",
    "Chance of escalation": "A calibrated forecast that the provider gets a strong alert or confirmed case within the "
                            "horizon. Used to order the queue; never counted as evidence.",
    "Must-take": "Cases the policy says must be worked this week (MFCU referrals or severity 5). They get capacity "
                 "first; if they do not fit they are flagged over capacity, never dropped.",
    "Mandate": "A signed statement: the policy (signed by an SIU lead), each decision (signed by the person deciding) "
               "and each approval. Signatures are Ed25519 over the exact case, evidence and policy.",
    "Dual control": "High-impact actions (MFCU referral) execute only after a second, different SIU lead signs.",
    "PHI masking": "Minimum necessary: member ids show as tokens, birth dates as age bands and ZIP codes as 3 digits. "
                   "Revealing them needs a reason and is recorded in the ledger.",
    "Hash chain": "Each ledger block includes the hash of the previous one, so changing any block breaks every later "
                  "link and Verify points to it.",
}


def help(term: str) -> str:
    return TERMS[term]


def popover() -> None:
    """Sidebar glossary for first-time visitors."""
    with st.popover("Glossary", icon=":material/menu_book:", width="stretch"):
        for term, text in TERMS.items():
            st.markdown(f"**{term}**: {text}")


THRESHOLD_HELP = {
    "abstain.statistical_min": "Below this, a case backed only by peer comparison abstains (Needs more data).",
    "actions.PREPAY_REVIEW.any_of.1.min_class_score.statistical": "How unusual a provider's E/M level mix must be "
                                                                  "before prepay review is allowed on that alone.",
    "actions.PREPAY_REVIEW.any_of.1.min_conf": "Minimum confidence for the E/M upcoding path to prepay review.",
    "predictive.lift_min": "Forecast needed before it may lift a statistical-only case to prepay review.",
    "predictive.statistical_min": "Peer-comparison score also required for that forecast lift.",
    "actions.FULL_INVESTIGATION.min_conf": "Minimum evidence confidence for a full investigation.",
    "actions.REFER_TO_MFCU.min_conf": "Minimum evidence confidence for an MFCU referral (two evidence classes are "
                                      "always required).",
    "actions.REFER_TO_MFCU.min_dollars": "Minimum dollars at risk for an MFCU referral.",
    "capacity.hours_per_investigator_week": "Working hours per investigator per week; sets queue capacity.",
}

THRESHOLD_LABELS = {  # display labels: plain action names instead of policy enums
    "predictive.lift_min": "Predictive lift: 90-day forecast at least",
    "actions.FULL_INVESTIGATION.min_conf": "Full investigation: min confidence",
    "actions.REFER_TO_MFCU.min_conf": "Refer to MFCU: min confidence",
    "actions.REFER_TO_MFCU.min_dollars": "Refer to MFCU: min $ at risk",
}
