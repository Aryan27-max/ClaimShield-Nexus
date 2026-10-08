"""Capacity-aware SIU queue: priority score + greedy fill of investigator hours; overflow is deferred, never dropped."""
import pandas as pd

PREDICTIVE_AVAILABLE = False  # P5 replaces p_fwa(h) with the calibrated 30/60/90 model


def p_fwa(cases: pd.DataFrame, horizon: int = 90) -> pd.Series:
    """P(FWA within horizon). Until the predictive lens exists, the fused confidence stands in for every horizon."""
    return cases.confidence.astype(float)


def rank(cases: pd.DataFrame, policy: dict, investigators: int | None = None,
         hours_per_week: float | None = None, horizon: int = 90) -> pd.DataFrame:
    """Adds p_fwa, severity_w, priority, rank, cum_hours, status (in_capacity | deferred | not_queued)."""
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
    q = q.sort_values(["queued", "priority", "case_id"], ascending=[False, False, True]).reset_index(drop=True)
    used, status, cum = 0.0, [], []
    for is_q, h in zip(q.queued, q.est_hours):
        if not is_q:
            status.append("not_queued")
        elif used + h <= capacity:
            used += h
            status.append("in_capacity")
        else:
            status.append("deferred")
        cum.append(used)
    q["status"], q["cum_hours"] = status, cum
    q["rank"] = range(1, len(q) + 1)
    q.attrs.update(capacity_hours=capacity, used_hours=used, horizon=horizon, predictive_available=PREDICTIVE_AVAILABLE)
    return q
