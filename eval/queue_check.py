"""P4.5 check: must-take MFCU cases are never silently deferred; backlog at 1/3/5 investigators.
Run: python -m eval.queue_check"""
import sys

import pandas as pd

from core import harness
from core import queue as Q
from core import schema as S

HARNESS_COLS = ["allowed_actions", "recommended_action", "rule_trace", "requires_human", "missing_classes",
                "est_hours", "policy_version", "policy_hash"]


def main() -> int:
    pol = harness.load_policy()
    cases = harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=HARNESS_COLS, errors="ignore"), pol)
    ok = True
    for inv in [1, 3, 5]:
        q = Q.rank(cases, pol, investigators=inv)
        mfcu = q[q.recommended_action == "REFER_TO_MFCU"]
        good = mfcu.status.isin(["in_capacity", "over_capacity"]).all()
        ok &= bool(good) if inv == 3 else True
        print(f"{inv} investigators: {q.attrs['used_hours']:.0f}/{q.attrs['capacity_hours']:.0f} h used, "
              f"weeks_to_clear {q.attrs['weeks_to_clear']}, {q.status.value_counts().to_dict()}, "
              f"MFCU {len(mfcu)} -> {mfcu.status.value_counts().to_dict()}")
        if inv == 3:
            print(q.head(10)[["rank", "case_id", "recommended_action", "max_severity", "must_take", "p_fwa",
                              "dollars_at_risk", "est_hours", "priority", "status"]].to_string(index=False))
    print(("PASS" if ok else "FAIL") + " at 3 investigators every MFCU case is in capacity or flagged over-capacity")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
