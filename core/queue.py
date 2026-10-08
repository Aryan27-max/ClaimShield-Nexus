"""Capacity-aware SIU queue: priority score + greedy fill of investigator hours; overflow is deferred, never dropped."""
import pandas as pd

PREDICTIVE_AVAILABLE = False  # P5 replaces p_fwa(h) with the calibrated 30/60/90 model


def p_fwa(cases: pd.DataFrame, horizon: int = 90) -> pd.Series:
    """P(FWA within horizon). Until the predictive lens exists, the fused confidence stands in for every horizon."""
    return cases.confidence.astype(float)


def _must_take(q: pd.DataFrame, policy: dict) -> pd.Series:
    mt = policy.get("must_take", {})
    hit = q.recommended_action.isin(mt.get("actions", [])) | (q.max_severity >= mt.get("min_severity", 99))
    return q.queued & hit


def rank(cases: pd.DataFrame, policy: dict, investigators: int | None = None,
         hours_per_week: float | None = None, horizon: int = 90) -> pd.DataFrame:
    """Adds p_fwa, severity_w, priority, must_take, rank, cum_hours and status:
    in_capacity | over_capacity (must-take that doesn't fit: escalate) | deferred | not_queued."""
    cap = policy["capacity"]
    investigators = cap["investigators"] if investigators is None else investigators
    hours_per_week = cap["hours_per_investigator_week"] if hours_per_week is None else hours_per_week
    capacity = investigators * hours_per_week
    sw = {int(k): v for k, v in policy["severity_weights"].items()}
    q = cases.copy()
    q["p_fwa"] = p_fwa(q, horizon)
    q["severity_w"] = q.max_severity.map(sw).fillna(1.0)
    q["priority"] = (q.p_fwa * q.dollars_at_risk * q.severity_w * q.member_harm_w / q.est_hours.clip(lower=1)).round(2)
    q["queued"] = ~q.recommended_action.isin(cap["no_capacity_actions"])
    q["must_take"] = _must_take(q, policy)
    q = q.sort_values(["queued", "must_take", "priority", "case_id"],
                      ascending=[False, False, False, True]).reset_index(drop=True)
    used, status, cum = 0.0, [], []
    for is_q, must, h in zip(q.queued, q.must_take, q.est_hours):
        if not is_q:
            status.append("not_queued")
        elif used + h <= capacity:
            used += h
            status.append("in_capacity")
        else:
            status.append("over_capacity" if must else "deferred")
        cum.append(used)
    q["status"], q["cum_hours"] = status, cum
    q["rank"] = range(1, len(q) + 1)
    queued_h = float(q.est_hours[q.queued].sum())
    q.attrs.update(capacity_hours=capacity, used_hours=used, queued_hours=queued_h, horizon=horizon,
                   weeks_to_clear=round(queued_h / capacity, 1) if capacity else float("inf"),
                   predictive_available=PREDICTIVE_AVAILABLE)
    return q
