# Code review

Full read of `core/`, `ui/`, `eval/`, `data/gen/`, `tests/` and `policy/` (session S8). Each finding was reproduced by running the code, not inferred. Severity: **bug** (wrong result or crash), **risk** (fails under plausible conditions or weakens a guarantee), **cleanup** (clarity, size, dead code). The Status column records the outcome of the fix pass.

## Findings

| # | File | Issue | Severity | Fix | Status |
|---|---|---|---|---|---|
| 1 | `core/fusion.py` | `build_cases` raises `AttributeError` when there are no alerts (for example, a clean data set). | bug | Return an empty case frame with the full column set. The UI then shows a "no cases" state. | fixed |
| 2 | `core/harness.py` | Policy values are never validated. Negative hours give a negative weeks-to-clear, thresholds > 1 are accepted, and a missing key fails deep inside `evaluate` with `KeyError`. | bug | `validate_policy()` runs on load, preview and save, and lists every problem in one clear `ValueError`. | fixed |
| 3 | `core/harness.py` | `save_version` fails with "max() arg is an empty sequence" in a folder without versions. Saving an unchanged policy creates a duplicate version. | bug | Start at v1 when the folder is empty, and reject a save with no threshold change. | fixed |
| 4 | `core/harness.py` | An unsaved preview with zero changes gets a different hash from the active policy (same content, different hash). | bug | No changes ⇒ return the active policy and its hash. The hash is deterministic in content. | fixed |
| 5 | `ui/pages/5_Policy.py` | Number inputs accept negative dollars or hours, which ends in a traceback. | bug | Bounded inputs plus a friendly error message. | fixed |
| 6 | `ui/app.py` | If the selected policy file is deleted (for example, a demo reset removes `harness_v2.yaml`), every page crashes with `FileNotFoundError`. | bug | Fall back to the first available version and say so. | fixed |
| 7 | `ui/pages/1_Overview.py`, `2_Queue.py`, `3_Case.py`, `4_Network.py` | The headers read `q.policy_hash.iloc[0]`, and the Case and Network pages assume at least one case, so they raise `IndexError` when there are no cases. | bug | Shared empty-state guard with a friendly message. Headers take the hash from the policy. | fixed |
| 8 | `core/queue.py` | Greedy fill with skipping: adding investigators can move a small backfill case off the slate (P0037 at 1→2 investigators, P0984 at 2→3) when a must-take MFCU case now fits. Strict monotonicity contradicts must-take-first: a monotone incremental fill drops MFCU in-capacity at 3 investigators from 6 to 4. | risk (by design) | Kept must-take-first and documented the rule. A case leaves the slate only when a higher-ranked case takes its hours, and it becomes `deferred` (never dropped). A test guards this. | documented + tested |
| 9 | `core/ledger.py` | Two sessions appending at the same time race for the next `idx`, so the second fails with `IntegrityError`. | risk | `BEGIN IMMEDIATE` serialises writers. | fixed |
| 10 | `core/ledger.py` | Connections opened with `with sqlite3.connect()` are committed but never closed. | risk | Close every connection explicitly. | fixed |
| 11 | `core/brief.py` | The header cites the next ledger index, which is computed before the append. A concurrent append makes the citation wrong. | risk | Build the brief inside the ledger write transaction (payload callable receives the index). | fixed |
| 12 | `core/schema.py` | `load()` on a missing `data/out` raises a bare `FileNotFoundError` with no guidance. | risk | Message names the command to run (`python -m data.gen.synth`). | fixed |
| 13 | `ui/pages/1_Overview.py` | A cold load trains three models for the baseline card (2–4 s, against the < 3 s target). | risk | `core/predict` computes baseline and new-onset metrics during the pipeline run and stores them in `run_meta` and the `model_run` ledger block. Overview reads them. | fixed |
| 14 | `ui/pages/1_Overview.py` | The synthetic-validation section crashes when `ground_truth.parquet` is absent (real data). | risk | Shows an information note instead. | fixed |
| 15 | `ui/style.py` | `page_header` inserts the subtitle into HTML without escaping. | risk | `html.escape`. | fixed |
| 16 | `ui/app.py`, `ui/pages/3_Case.py`, `ui/pages/5_Policy.py` | Unexpected errors (brief generation, policy write) render as raw tracebacks. | risk | Friendly error box with an expandable details panel. Streamlit control flow (`BaseException`) is untouched. | fixed |
| 17 | `tests/test_pipeline.py` | The pipeline test overwrites `data/out` and `models/`. `run_meta.ledger_idx` then points into the temporary ledger. | risk | Test runs against a temporary copy of the inputs, outputs and models. | open |
| 18 | `eval/pipeline_check.py` | Each run re-runs the pipeline and appends 5 blocks to the demo ledger. | risk | Reads existing outputs by default; `--run` re-runs. | open |
| 19 | `core/harness.py` (`THRESHOLDS`) | The positional path `any_of.1` breaks the Policy page if a policy reorders the PREPAY branches. | risk | The page lists only thresholds that resolve in the selected policy and names the missing ones. | fixed |
| 20 | `core/brief.py`, `ui/pages/4_Network.py` | Ring network context reports the first member's Louvain community even when members sit in different communities. | cleanup (misleading) | List each distinct community. | fixed |
| 21 | `core/predict.py` | `split()` raises a bare `IndexError` when history is too short for the embargoed calibration window. | cleanup | Explicit `ValueError` with the reason. | fixed |
| 22 | `data/gen/schemes.py` | 268 lines (limit 250). | cleanup | Legit outliers and honest errors move to `data/gen/outliers.py`. Same RNG call order, so the data is byte-identical (verified by parquet hashes). | fixed |
| 23 | `core/harness.py` | 246 lines; validation would push it past 250. | cleanup | Policy editing and versioning move to `core/policy_edit.py`. | fixed |
| 24 | `core/fusion.py` | `load_alerts()` is never called. | cleanup | Removed. | fixed |
| 25 | `core/queue.py`, `core/pipeline.py` | The `PREDICTIVE_AVAILABLE` flag is a P3 leftover that is always `True`. | cleanup | Removed. | fixed |
| 26 | `ui/pages/1_Overview.py`, `2_Queue.py` | Subtitles read `st.session_state` directly and print "None investigators" when a page renders before the sidebar (AppTest `switch_page`). | cleanup | Shared `C.investigators()` / `C.horizon()` helpers with policy defaults. | fixed |

## Verified, no issue

| Area | Check | Result |
|---|---|---|
| Human in the loop | `harness.decide` is the only writer of `decisions` rows and `human_decision` blocks (grep across `core/`, `ui/`, `eval/`). It re-evaluates the case and rejects actions outside `allowed_actions`, an empty `user_id`, and unknown reason codes. | ok |
| Fail-safe | Statistical-only below `abstain.statistical_min` or completeness below `min_completeness` ⇒ `NEEDS_MORE_DATA` with only safe actions allowed. Predictive is kept out of `classes` and confidence. | ok |
| Evidence | Every rules, anomaly and graph alert carries evidence rows (field, value, expected, source); enforced by the lens tests. | ok |
| Ground-truth isolation | No module in `core/` references `ground_truth` or `legit_outliers` (test). Only `eval/` and the clearly labelled validation sections of the UI read them. | ok |
| Audit | Ledger blocks for lens runs, model run, fusion run (policy hash + Merkle root), policy changes, briefs and human decisions. | ok |
| Dates and windows | Labels on (T, T+h] only when T+h ≤ data end; features ≤ T; investigations `closed < T`; anomaly 90-day window (asof−90, asof]; data dates are timezone-naive, ledger timestamps are UTC. | ok |
| pandas pitfalls | Every groupby on a categorical column uses `observed=True` or casts to `str` first. Ratios guard against division by zero (`np.maximum`, `.where(scale > 0)`). | ok |
| Determinism | `SEED=42` drives every RNG (generator, IsolationForest, Louvain, LightGBM). The generator is byte-identical across runs (test). | ok |
| Security | YAML only via `safe_load` / `safe_dump`. No `eval` / `exec`. SQL is parameterised. File paths are never user-controlled (new policy path = fixed folder + next version number). The HTML brief export escapes every value. | ok |
