# Demo script (4 minutes)

Setup: app open on **Overview**, sidebar at 3 investigators, 90-day horizon, policy v1. Fresh ledger (see the checklist at the end).

| Time | Page | Click | Talking point |
|---|---|---|---|
| 0:00–0:35 | Overview | Point to the funnel tiles, then the "99.3% alert reduction" chart. Scroll to *Synthetic validation*. | "9,061 flagged claim lines become 63 cases that need an investigator, and 7 fit this week. On planted schemes we catch every ring, kickback and phantom provider, and zero clean providers or legitimate outliers get escalated." |
| 0:35–1:05 | SIU Queue | Note *Over capacity* = 9. Drag **Investigators** in the sidebar from 3 to 5. | "The queue is sized to real hours. With 5 investigators every MFCU referral fits (MFCU over-capacity goes from 3 to 0). The 5 cases still over capacity are flagged for the SIU lead, never silently dropped." |
| 1:05–1:40 | Case | **Open case** → pick `RING-P0007`. Show the **Evidence** tab, then the **Network** tab (toggle on the ego graph). | "Five providers share one owner, address and bank, with referral loops between them. Every row cites claim, field, value and expected value." |
| 1:40–2:05 | Case | **Risk forecast** tab, then **Brief** tab → **Generate brief** → **Download .html**. | "The forecast is an early warning, not evidence. The brief is a deterministic template: same data, same brief. Its SHA-256 just went into the ledger." |
| 2:05–2:30 | Case | Scroll to **Human decision**: user id `siu.lead`, action `REFER_TO_MFCU`, reason `EVIDENCE_CORROBORATED` → **Record decision**. | "Only a human can choose the action, only from what policy allows, and only with a reason code. That is ledger block #N." |
| 2:30–3:15 | Policy | Set **Abstain** to 0.40, **E/M upcoding path: statistical score floor** to 0.55 and **min confidence** to 0.40 → **Preview impact**. Then enter author and reason → **Save as new version**. | "The human defines the rules. The preview shows upcoders at prepay review going from 1 to 5 with zero clean providers escalated. Saving writes v2, hashes it into the ledger and re-ranks the queue." |
| 3:15–3:45 | Audit Ledger | **Verify chain** (green). Open **Demo controls** → **Simulate tamper** on a decision block → **Verify chain** (red). | "Change one byte in history and verification points to the exact broken block." |
| 3:45–4:00 | — | — | "Machines find evidence. Humans make decisions. The ledger proves it." |

Backup answers:
- *Does the model beat the baseline?* No, not on already-flagged providers: a naive "flagged before" persistence baseline is as good or better, and we show both on Overview. The forecast is an early warning for providers without flag history. We found train/test leakage and fixed it with an embargo; the numbers shown are post-fix. It ranks the queue but never counts as evidence.
- *What changes on the Policy page?* Only the E/M lever: upcoding at PREPAY+ goes from 1 to 5 with zero clean providers escalated.
- *Upcoding recall is low?* Peer comparison alone is not enough to accuse anyone. The policy abstains until a human lowers the threshold or records evidence arrives.

## Demo checklist (10 minutes before)

```bash
cd ~/dev/claimshield && git status --short          # clean tree
find policy -name 'harness_v*.yaml' ! -name harness_v1.yaml -delete   # drop rehearsal versions
.venv/bin/python -m data.gen.synth && .venv/bin/python -m core.pipeline --reset-ledger
.venv/bin/python -m pytest -q                        # all green
.venv/bin/streamlit run ui/app.py                    # open Overview once to warm the cache
```
