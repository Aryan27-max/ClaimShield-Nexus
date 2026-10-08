"""Policy schema: action names, evidence classes and validation of human-authored policy YAML."""
ACTIONS = ["MONITOR", "NEEDS_MORE_DATA", "PROVIDER_EDUCATION", "PREPAY_REVIEW", "FULL_INVESTIGATION", "REFER_TO_MFCU"]
SAFE = ["NEEDS_MORE_DATA", "MONITOR"]
EVIDENCE_CLASSES = ["deterministic", "structural", "statistical"]
PROGRAMS = ["medicaid", "medicare_ab", "medicare_advantage", "part_d"]
REQUIRED = ["version", "class_map", "class_weights", "completeness", "abstain", "actions", "severity_weights",
            "member_harm", "est_hours", "capacity", "reason_codes"]
CONDITIONS = {"min_classes", "min_conf", "min_dollars", "max_dollars", "min_severity", "max_severity", "classes_any",
              "classes_all", "codes_any", "min_class_score", "predictive_lift", "any_of", "requires_human"}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_policy(pol: dict) -> dict:
    """Raises ValueError listing every problem: missing keys, probabilities outside [0, 1], negative $ or hours."""
    errs = [f"missing key '{k}'" for k in REQUIRED if k not in pol]
    if errs:
        raise ValueError("invalid policy: " + "; ".join(errs))

    def check(path: str, v, lo: float, hi: float, integer: bool = False) -> None:
        if not _num(v) or not lo <= v <= hi or (integer and v != int(v)):
            errs.append(f"{path} = {v!r} must be {'an integer' if integer else 'a number'} in [{lo:g}, {hi:g}]")

    def cond(path: str, c: dict) -> None:
        for k, v in (c or {}).items():
            p = f"{path}.{k}"
            if k not in CONDITIONS:
                errs.append(f"{p}: unknown condition")
            elif k == "any_of":
                for i, sub in enumerate(v):
                    cond(f"{p}.{i}", sub)
            elif k == "min_conf":
                check(p, v, 0, 1)
            elif k == "min_class_score":
                for c_, x in v.items():
                    check(f"{p}.{c_}", x, 0, 1)
            elif k in ("min_dollars", "max_dollars"):
                check(p, v, 0, float("inf"))
            elif k in ("min_severity", "max_severity"):
                check(p, v, 1, 5, integer=True)
            elif k == "min_classes":
                check(p, v, 1, len(EVIDENCE_CLASSES), integer=True)

    for c, w in pol["class_weights"].items():
        check(f"class_weights.{c}", w, 0, 1)
    for k in ("statistical_min", "min_completeness"):
        check(f"abstain.{k}", pol["abstain"].get(k), 0, 1)
    for k in ("lift_min", "statistical_min") if "predictive" in pol else ():
        check(f"predictive.{k}", pol["predictive"].get(k), 0, 1)
    for a in ACTIONS:
        if a not in pol["actions"]:
            errs.append(f"actions.{a} missing")
        check(f"est_hours.{a}", pol["est_hours"].get(a), 0, 168)
    check("est_hours.per_extra_provider", pol["est_hours"].get("per_extra_provider"), 0, 168)
    for a, c in pol["actions"].items():
        cond(f"actions.{a}", c)
    check("capacity.investigators", pol["capacity"].get("investigators"), 1, 1000, integer=True)
    check("capacity.hours_per_investigator_week", pol["capacity"].get("hours_per_investigator_week"), 1, 168)
    bad = set(pol.get("must_take", {}).get("actions", [])) - set(ACTIONS)
    errs += [f"must_take.actions: unknown action {a}" for a in sorted(bad)]
    if not pol["reason_codes"]:
        errs.append("reason_codes must not be empty")
    errs += [f"dual_control_actions: unknown action {a}" for a in pol.get("dual_control_actions", []) if a not in ACTIONS]
    errs += [f"automation_scope: {a} is not a safe routing action (default-deny automation)"
             for a in pol.get("automation_scope", []) if a not in SAFE]
    errs += [f"{k}: unknown program {p}" for k in ("program", "allow_pause_programs")
             for p in ([pol[k]] if isinstance(pol.get(k), str) else pol.get(k, [])) if p not in PROGRAMS]
    if errs:
        raise ValueError("invalid policy: " + "; ".join(errs))
    return pol


def regulatory_basis(policy: dict, action: str | None = None, codes=()) -> list[tuple[str, str]]:
    """[(topic, citation)] from the policy's `regulatory_basis` for an action and the case's rule codes."""
    rb = policy.get("regulatory_basis", {})
    out = [(action, rb.get("actions", {})[action])] if action in rb.get("actions", {}) else []
    return out + [(c, rb.get("rules", {})[c]) for c in sorted(set(codes)) if c in rb.get("rules", {})]
