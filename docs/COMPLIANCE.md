# Compliance map (US payer)

**Not legal advice; citations for orientation; state rules vary.** Items marked *state-specific* must be checked against the program's own state rules. Citations come only from the vetted list kept in the policy file (`policy/harness_v1.yaml`, `regulatory_basis`); the rule trace, Case page and investigation brief show them next to the action they support.

Design rule: **obligations are created only from human, executed decisions, never from model scores.** A decision executes only when its signatures verify (see "Signed mandates" below).

## Requirements

| Requirement | Citation | Where implemented | How verified |
|---|---|---|---|
| Payment-suspension determination on a credible allegation of fraud: suspend, or document good cause (law-enforcement request, member access to care, other documented good cause) | 42 CFR 455.23 | `core/compliance.py` `on_executed` creates the determination when REFER_TO_MFCU executes; `record_suspension` (Case → Compliance tab) | `tests/test_compliance.py` |
| Written MFCU referral no later than the next business day | 42 CFR 455.23 | `next_business_day` (weekends skipped) sets the referral due date at execution | `tests/test_compliance.py` (Friday → Monday, Saturday → Monday) |
| MFCU certification every 90 days while the referral is open | 42 CFR 455.23 | Certification due at execution + 90 days; marking it met schedules the next one | `tests/test_compliance.py` |
| Managed care plan suspends payments when the State directs | 42 CFR 438.608(a)(8) | Cited in the REFER_TO_MFCU basis (rule trace, Case page, brief) | `tests/test_compliance.py` (basis in rule trace) |
| Preliminary investigation, full investigation, resolution | 42 CFR 455.14–455.16 | Basis for FULL_INVESTIGATION; human decision workflow with reason codes | Rule trace / brief tests |
| Prepayment review | State Medicaid prepayment review authority (*state-specific: verify*) | Basis for PREPAY_REVIEW | Rule trace |
| Provider education for non-fraud billing errors | State / CMS program integrity practice (*verify*) | Basis for PROVIDER_EDUCATION | Rule trace |
| Excluded-provider screening (OIG LEIE / SAM) and the effect of exclusion | 42 CFR 455.436; 42 CFR 1001.1901 | Rule R07 (billing by an excluded provider) with its basis | `tests/test_rules.py` (R07) |
| Medicaid NCCI methodologies: procedure-to-procedure edits and medically unlikely edits | ACA §6507 | Rules R02 (PTP) and R03 (MUE) with their basis | `tests/test_rules.py` |
| Report and return an identified overpayment within 60 days | 42 U.S.C. 1320a-7k(d) | Reason code OVERPAYMENT_IDENTIFIED (with amount) creates a 60-day return obligation | `tests/test_compliance.py` |
| Good-faith investigation pause of up to 180 days for Medicare A/B; none for MA or Part D | 42 CFR 401.305; 42 CFR 422.326; 42 CFR 423.360 | `pause()` allowed only when the policy `program` is in `allow_pause_programs` (default program: medicaid, so the pause is disabled with an explanation) | `tests/test_compliance.py` |
| HIPAA minimum necessary | 45 CFR 164.502(b) | `core/phi.py`: member ids as keyed tokens, DOB as age band, ZIP as 3 digits in tables and briefs; reveal needs a reason; auditors cannot reveal | `tests/test_phi.py` |
| HIPAA audit controls | 45 CFR 164.312(b) | Ledger blocks for `case_viewed`, `phi_access`, decisions, mandates and compliance events | `tests/test_phi.py`, `tests/test_ledger.py` |
| HIPAA integrity | 45 CFR 164.312(c)(1) | SHA-256 hash chain (`ledger.verify`) and Ed25519 signatures (`mandate.verify_signatures`); tampering fails both at the same block | `tests/test_mandate.py`, `tests/test_ui.py` |
| Record retention (10 years; setting is displayed, not enforced) | 42 CFR 438.3(u); 42 CFR 422.504(d) | Policy `record_retention_years` shown on the Policy page | Display only |

## Signed mandates (internal control, AP2-inspired)

Not a regulation: an internal control that makes every enforcement step attributable and verifiable.

| Control | Where implemented | How verified |
|---|---|---|
| Policy (intent mandate) signed by an SIU lead; a missing, invalid or revoked policy mandate blocks every decision | `core/mandate.py` `issue_policy`, `policy_status`; `harness.decide` | `tests/test_mandate.py` |
| Decision (cart mandate) signed by the deciding investigator or lead, bound to case, evidence and policy hashes; auditors cannot decide | `mandate.sign_decision`, `mandate.check_decision` | `tests/test_mandate.py` |
| Dual control (four-eyes): REFER_TO_MFCU stays PENDING_APPROVAL until a different SIU lead signs the execution mandate | `mandate.approve` | `tests/test_mandate.py`, `tests/test_ui.py` |
| Default-deny automation: the system actor may only route MONITOR / NEEDS_MORE_DATA | Policy `automation_scope`; `mandate.check_decision` | `tests/test_mandate.py` |
| Revocation of a pending decision or a policy version by an SIU lead | `mandate.revoke` | `tests/test_mandate.py` |

## Limitations

- Synthetic data only; no real PHI is processed. The masking and access controls show the design, not a certified implementation.
- Federal holidays are not handled in the next-business-day calculation (weekends only).
- No integration with an MFCU case system, a payment system or the OIG LEIE / SAM services; obligations are tracked, not transmitted.
- Demo signing keys live on disk in `data/out/keys/`. Production would use SSO identities and keys held in an HSM or KMS.
- Record retention is displayed as a setting and not enforced by deletion rules.
- State Medicaid rules differ; the state-specific items above need local legal review.
