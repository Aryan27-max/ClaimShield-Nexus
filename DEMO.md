# Demo script (about 4 minutes 25 seconds)

Setup: app open on **Overview**, sidebar signed in as **inv.a**, 3 investigators, 90-day horizon, policy v1 (signed by siu.lead at reset). Fresh ledger (see the checklist at the end).

| Time | Page | Click | Talking point |
|---|---|---|---|
| 0:00–0:35 | Overview | Point to the funnel tiles, then the "99.3% alert reduction" chart. Scroll to *Synthetic validation*. | "9,061 flagged claim lines become 63 cases that need an investigator, and 7 fit this week. We catch every planted ring, kickback and phantom provider, and zero clean providers or legitimate outliers get escalated." |
| 0:35–1:00 | SIU Queue | Note *Over capacity* = 9. Drag **Investigators** in the sidebar from 3 to 5. | "The queue is sized to real hours. With 5 investigators every MFCU referral fits (MFCU over-capacity 3 → 0); the 5 still over capacity are flagged for the SIU lead, never dropped." |
| 1:00–1:35 | Case | **Open case** → `RING-P0007`. **Evidence** tab (scroll to the masked members), then **Network** tab (toggle the ego graph). | "Five providers share one owner, address and bank, with referral loops. Every row cites claim, field, value and expected value, and member identities stay masked unless someone records a reason." |
| 1:35–1:55 | Case | **Risk forecast** tab, then **Brief** → **Generate brief** → **Download .html**. | "The forecast is an early warning, not evidence. The brief is a deterministic template with the regulatory basis and the authorisation chain; its SHA-256 is in the ledger." |
| 1:55–2:40 | Case | As **inv.a**: action **Refer to MFCU**, reason `EVIDENCE_CORROBORATED` → **Sign & submit** (status: pending approval). Sidebar **Signed in as** → **siu.lead** → **Approve (second signature)**. Open the **Compliance** tab. | "The investigator signs a decision bound to this exact case, evidence and policy. MFCU referral is dual control: it only executes when a different SIU lead signs. Now the obligations appear: suspension determination and written MFCU referral due the next business day, certification every 90 days." |
| 2:40–3:20 | Policy | Still as **siu.lead**: set **Abstain** 0.40, **E/M upcoding path: statistical score floor** 0.55, **min confidence** 0.40 → **Preview impact** → reason → **Sign & save as new version**. | "Humans define the rules: upcoders at prepay review go from 1 to 5 with zero clean providers escalated. Saving signs the new version; an unsigned policy blocks every decision." |
| 3:20–4:00 | Audit Ledger | **Verify chain** and **Verify signatures** (both green). **Demo controls** → **Simulate tamper** on the `decision_mandate` block (its number is in the signatures table) → **Verify chain** and **Verify signatures** again. | "Change one byte and both checks point to the same block: the hash chain breaks and the Ed25519 signature no longer verifies." |
| 4:00–4:15 | Any | Sidebar **Light / Dark** toggle. | "Light or dark, it stays readable: every colour pair passes WCAG AA, and the choice sticks across pages." |
| 4:15–4:25 | — | — | "Machines find evidence. Humans make decisions. The ledger proves it." |

Backup answers:
- *Does the model beat the baseline?* No, not on already-flagged providers: a naive "flagged before" persistence baseline is as good or better, and we show both on Overview. The forecast is an early warning for providers without flag history. Train/test leakage was found and fixed with an embargo; the numbers shown are post-fix. It ranks the queue but never counts as evidence.
- *What changes on the Policy page?* Only the E/M lever: upcoding at PREPAY+ goes from 1 to 5 with zero clean providers escalated.
- *Why not blockchain or Solana?* Claims and decisions are PHI under HIPAA: replicating them to a public chain is a disclosure, and immutable public storage conflicts with correction and retention duties. A permissioned chain adds consortium overhead to what is one organisation's audit trail. The properties we need are tamper evidence and non-repudiation, which a SHA-256 hash chain plus Ed25519 signatures in the payer's own database provide.
- *What regulations does this map to?* 42 CFR 455.23 (payment suspension and MFCU referral), 455.14–455.16 (investigations), 455.436 (exclusion checks), Medicaid NCCI under ACA §6507, 42 U.S.C. 1320a-7k(d) (60-day overpayments; 42 CFR 401.305 pause for Medicare A/B only), and HIPAA 45 CFR 164.502(b), 164.312(b) and 164.312(c)(1). The full map is in docs/COMPLIANCE.md. Not legal advice; state rules vary.

## Demo checklist (10 minutes before)

```bash
git status --short                                   # from the repo root: clean tree
find policy -name 'harness_v*.yaml' ! -name harness_v1.yaml -delete   # drop rehearsal versions
.venv/bin/python -m data.gen.synth && .venv/bin/python -m core.pipeline --reset-ledger   # re-signs v1 as siu.lead
.venv/bin/python -m pytest -q                        # all green
.venv/bin/streamlit run ui/app.py                    # open Overview once to warm the cache
```
