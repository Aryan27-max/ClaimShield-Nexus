# ClaimShield Nexus — Architecture

## 1. User journey
**Input:** SIU lead selects data snapshot, horizon (30/60/90), investigator capacity, and policy version.
**System:** runs 4 lenses → fuses evidence → applies human-authored harness → ranks by capacity.
**Output:** ranked cases, each with an evidence-cited brief, confidence, limitations and allowed actions.
**Uncertain:** case is routed to `NEEDS_MORE_DATA` with the missing evidence listed; it is never escalated automatically.
**Decision:** only a human picks the action; it is hash-chained into the ledger.

## 2. System overview
```mermaid
flowchart LR
  subgraph DATA[Synthetic Data Layer]
    G[synth.py<br/>planted schemes] --> T[(claims, members,<br/>providers, facilities,<br/>referrals, owners,<br/>investigations)]
    G --> GT[(ground_truth<br/>eval only)]
  end

  subgraph LENSES[Detection Lenses]
    R[Rules<br/>NCCI/MUE/dup/timing]
    A[Anomaly<br/>peer z + IsolationForest]
    N[Graph<br/>communities + risk propagation]
    P[Predict<br/>LightGBM 30/60/90 + SHAP]
  end

  T --> R & A & N & P
  R & A & N & P --> F[Fusion<br/>entity cases, evidence strength,<br/>calibrated confidence, abstain]
  F --> H{Decision Harness<br/>policy YAML v#}
  H --> Q[Capacity-aware SIU Queue]
  Q --> B[Brief Generator<br/>deterministic template]
  B --> UI[Streamlit UI]
  UI --> HU((Human Investigator))
  HU -->|action + reason code| L[(Hash-chained Ledger)]
  R & A & N & P & H -.log.-> L
  GT -.-> E[Eval: recall per scheme,<br/>alert-collapse funnel] --> UI
```

## 3. Data model
```mermaid
erDiagram
  MEMBER ||--o{ CLAIM : receives
  PROVIDER ||--o{ CLAIM : bills
  FACILITY ||--o{ CLAIM : "rendered at"
  PROVIDER ||--o{ REFERRAL : "refers (from)"
  PROVIDER ||--o{ REFERRAL : "receives (to)"
  OWNER ||--o{ PROVIDER : owns
  ADDRESS ||--o{ PROVIDER : "located at"
  ADDRESS ||--o{ FACILITY : "located at"
  PROVIDER ||--o{ INVESTIGATION : "subject of"
  CLAIM {
    string claim_id
    string member_id
    string provider_id
    string facility_id
    string referring_provider_id
    date service_date
    string cpt
    int units
    float paid_amt
  }
  PROVIDER {
    string provider_id
    string specialty
    string type
    string owner_id
    string address_id
    string bank_id
  }
```

## 4. Graph model (lens 3)
```mermaid
flowchart LR
  P1((Provider A)) -- refers --> P2((DME Supplier B))
  P2 -- refers --> P3((Lab C))
  P3 -- refers --> P1
  O[Owner X] -. owns .-> P2 & P3
  AD[Address 12] -. shared .-> P2 & P3
  M1((Member 1)) & M2((Member 2)) -- treated by --> P1 & P2 & P3
```
Signals: Louvain community density, shared owner/address/bank, referral reciprocity & concentration, member overlap (Jaccard), personalized PageRank seeded from confirmed past investigations.

## 5. Prediction (lens 4)
```mermaid
flowchart LR
  H[Data with service_date <= T] --> FE[Provider x month-end snapshot T<br/>volume/paid + 3m trend, E/M hi share, units/claim, PMPM,<br/>new-member ratio, rule-flagged claims <= T, trailing peer z,<br/>graph @ quarter end <= T, investigations closed < T, type, tenure]
  FE --> M30[LightGBM h=30] & M60[LightGBM h=60] & M90[LightGBM h=90]
  LBL["Label(h): strong alert on claims in (T, T+h]<br/>OR confirmed investigation opened"] --> M30 & M60 & M90
  M30 & M60 & M90 --> CAL[Isotonic on held-out train slice] --> S[p_fwa h + SHAP top-3 drivers]
```
- Snapshots from month 4 to the last T where T+h fits; latest snapshot (T = end of data) is scored for the queue.
- Strong alert = deterministic/structural score >= 0.6 or anomaly score >= 0.86. Rule flags are bucketed by service month (rules are not re-run per snapshot).
- Time split: fit T <= 2024-10, calibrate T in 2024-11..12, test T >= 2025-01. LightGBM num_threads=4, 300 trees, 15 leaves, seed 42. A `model_run` ledger block records params hash, ranges and metrics.
- Leakage guard: a test rebuilds features from data truncated at T0 and asserts identical rows for every T <= T0.
- The forecast is **not evidence**: it stays out of evidence classes and confidence, never counts for FULL_INVESTIGATION / REFER_TO_MFCU, and can only lift a strong statistical-only case to PREPAY_REVIEW (policy `predictive.lift_min`, `predictive.statistical_min`). It drives queue `p_fwa(h)`.

## 6. Decision harness & human-in-the-loop
```mermaid
stateDiagram-v2
  [*] --> Scored
  Scored --> NEEDS_MORE_DATA: only statistical AND score < statistical_min, OR low completeness
  Scored --> MONITOR: low risk
  Scored --> Eligible: policy conditions met
  Eligible --> PROVIDER_EDUCATION
  Eligible --> PREPAY_REVIEW
  Eligible --> FULL_INVESTIGATION
  Eligible --> REFER_TO_MFCU: >=2 classes AND $>=min AND conf>=min
  PROVIDER_EDUCATION --> HumanDecision
  PREPAY_REVIEW --> HumanDecision
  FULL_INVESTIGATION --> HumanDecision
  REFER_TO_MFCU --> HumanDecision
  NEEDS_MORE_DATA --> HumanDecision
  HumanDecision --> Ledger: action + reason_code + user_id
  Ledger --> [*]
```
Evidence classes: **deterministic** (rules), **structural** (graph), **statistical** (anomaly), **predictive** (P5; absent until then). Independence = distinct classes, not distinct alerts. Confidence = weighted noisy-OR of per-class max scores × data-completeness factor (no isotonic calibration until the predictive class lands in P5; 60 labels are too few). Abstain only when the case rests on statistical evidence alone below `abstain.statistical_min`, or data completeness is low; a strong single deterministic or structural signal may reach PREPAY_REVIEW / FULL_INVESTIGATION. MFCU always needs ≥ 2 classes + min $ + min confidence + a human.

Example policy (`policy/harness_v1.yaml`, abridged):
```yaml
version: 1
class_weights: {deterministic: 0.95, structural: 0.85, statistical: 0.55, predictive: 0.7}
abstain: {statistical_min: 0.75, min_completeness: 0.6}
actions:
  REFER_TO_MFCU:      {min_classes: 2, min_conf: 0.85, min_dollars: 25000, requires_human: true}
  FULL_INVESTIGATION: {min_conf: 0.75, min_dollars: 5000, any_of: [{min_classes: 2}, {classes_any: [structural], min_severity: 4}, {classes_any: [deterministic], min_severity: 4}]}
  PREPAY_REVIEW:      {min_conf: 0.55, classes_any: [deterministic, structural]}
  PROVIDER_EDUCATION: {classes_any: [deterministic, statistical], max_dollars: 5000}
weights: {severity: {1: 1, 3: 1.5, 5: 3}, member_harm: {bh: 2.0, home_health: 1.8, default: 1.0}}
capacity: {investigators: 3, hours_per_investigator_week: 30}
```

Queue: `priority = p_fwa(h) × $ at risk × severity_w × member_harm_w ÷ est_hours`. Must-take cases (policy `must_take`: REFER_TO_MFCU or severity ≥ 5) are filled first; a must-take case that doesn't fit is flagged `over_capacity` (escalate to SIU lead), never silently deferred. The rest fill greedily; overflow is `deferred`. Backlog = queued hours ÷ weekly capacity (weeks to clear).

## 7. Decision sequence
```mermaid
sequenceDiagram
  actor SIU as SIU Lead
  participant UI as Streamlit
  participant PL as Pipeline
  participant HZ as Harness
  participant LG as Ledger
  SIU->>UI: horizon=60, investigators=3, policy v1
  UI->>PL: run / load cached results
  PL->>LG: append lens outputs (hashes)
  PL->>HZ: fused cases
  HZ->>LG: append policy version + allowed actions
  HZ-->>UI: ranked queue + briefs
  SIU->>UI: open case, review evidence
  SIU->>UI: choose FULL_INVESTIGATION + reason
  UI->>LG: append human decision (prev_hash -> hash)
  SIU->>UI: Verify ledger
  UI->>LG: recompute chain
  LG-->>UI: OK / broken at block n
```

## 8. Audit ledger
Append-only SQLite table: `idx, ts, actor, event_type, payload_json, payload_sha, prev_hash, hash` where `hash = SHA256(prev_hash || payload_sha || ts || actor)`. `verify()` recomputes every hash and returns the first broken index. This gives tamper evidence without a blockchain and without exposing PHI.

## 9. Responsible AI
| Risk | Mitigation |
|---|---|
| False accusation | No auto-action; abstain band; ≥2 independent lenses for escalation; legit outliers in test data |
| Opaque scores | Evidence rows with field/value/expected; SHAP drivers; rule IDs |
| Bias by specialty/region | Peer groups per specialty+type; report flag rates by group on Overview |
| Silent policy change | Policy versions hashed into ledger |
| Data gaps | Completeness check lowers confidence, adds to limitations |
| Model drift | Time-split eval; precision tracked from investigator verdicts |
