"""Human policy editing: threshold paths, in-memory preview, impact diff, and versioned saves to the ledger.
Nothing here decides a case; it only changes the human-authored rules the harness applies."""
import copy
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from core import harness, identity, ledger
from core import mandate as M
from core import schema as S

THRESHOLDS = {  # dotted policy path -> label shown on the Policy page
    "abstain.statistical_min": "Abstain: statistical-only fused score below",
    "actions.PREPAY_REVIEW.any_of.1.min_class_score.statistical": "E/M upcoding path: statistical score floor",
    "actions.PREPAY_REVIEW.any_of.1.min_conf": "E/M upcoding path: min confidence",
    "predictive.lift_min": "Predictive lift: p_fwa(90) at least",
    "predictive.statistical_min": "Predictive lift: statistical score floor",
    "actions.FULL_INVESTIGATION.min_conf": "FULL_INVESTIGATION: min confidence",
    "actions.REFER_TO_MFCU.min_conf": "REFER_TO_MFCU: min confidence",
    "actions.REFER_TO_MFCU.min_dollars": "REFER_TO_MFCU: min $ at risk",
    "capacity.hours_per_investigator_week": "Hours per investigator per week",
}
META_KEYS = {"version", "name", "author", "created", "change_reason", "parent_hash"}


def _walk(d, path: str):
    *head, last = path.split(".")
    for k in head:
        d = d[int(k)] if isinstance(d, list) else d[k]
    return d, (int(last) if isinstance(d, list) else last)


def get_threshold(policy: dict, path: str):
    d, k = _walk(policy, path)
    return d[k]


def available_thresholds(policy: dict) -> dict:
    """THRESHOLDS that exist in this policy (a version may drop or reorder branches)."""
    out = {}
    for path, label in THRESHOLDS.items():
        try:
            get_threshold(policy, path)
            out[path] = label
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    return out


def content(policy: dict) -> dict:
    """The rules themselves: everything except hash/path and version metadata."""
    return {k: v for k, v in policy.items() if not k.startswith("_") and k not in META_KEYS}


def with_thresholds(policy: dict, values: dict) -> dict:
    """Unsaved, validated copy with dotted-path thresholds replaced. No effective change returns the active policy
    (same hash); otherwise `_hash` is a provisional hash that depends only on the content."""
    changed = {k: v for k, v in values.items() if get_threshold(policy, k) != v}
    if not changed:
        return policy
    pol = copy.deepcopy({k: v for k, v in policy.items() if not k.startswith("_")})
    for path, v in changed.items():
        d, k = _walk(pol, path)
        d[k] = v
    harness.validate_policy(pol)
    pol["_hash"] = hashlib.sha256(yaml.safe_dump(pol, sort_keys=True).encode()).hexdigest()
    pol["_path"] = "(unsaved preview)"
    return pol


def diff(cases: pd.DataFrame, old: dict, new: dict) -> pd.DataFrame:
    """Cases whose recommended action changes between two policies, with the first new rule-trace line as `why`."""
    base = cases.drop(columns=harness.OUTPUT_COLS, errors="ignore")
    a, b = harness.evaluate_all(base, old), harness.evaluate_all(base, new)
    ch = a.recommended_action != b.recommended_action
    why = [next((t for t in nt if t not in set(ot)), nt[0] if len(nt) else "")
           for ot, nt in zip(a.rule_trace[ch], b.rule_trace[ch])]
    return pd.DataFrame({"case_id": a.case_id[ch], "before": a.recommended_action[ch],
                         "after": b.recommended_action[ch], "why": why})


def _versions(folder: Path) -> list[int]:
    return [int(m.group(1)) for p in folder.glob("harness_v*.yaml") if (m := re.fullmatch(r"harness_v(\d+)", p.stem))]


def save_version(policy: dict, author: str, reason: str, old: dict, folder: Path | str | None = None, db=None) -> dict:
    """Writes policy/harness_vN.yaml (N = next free version; never overwrites), a `policy_change` ledger block and the
    new version's policy mandate signed by `author`, who must be an SIU lead."""
    if not str(author).strip() or not str(reason).strip():
        raise ValueError("author and change reason are required")
    if identity.role(author) != "siu_lead":
        raise ValueError(f"only an SIU lead can sign a new policy version ({author} is {identity.role(author)})")
    if content(policy) == content(old):
        raise ValueError("no threshold changed: nothing to save")
    harness.validate_policy(content(policy) | {"version": 1})
    folder = Path(folder or Path(S.POLICY).parent)
    n = max(_versions(folder) + [int(old["version"])]) + 1
    path = folder / f"harness_v{n}.yaml"
    body = {**content(policy), "version": n, "name": f"harness_v{n}", "author": author,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "change_reason": reason,
            "parent_hash": old["_hash"]}
    with open(path, "x") as f:
        f.write("# Human-authored decision policy. Models propose; this policy constrains; a human decides.\n")
        yaml.safe_dump(body, f, sort_keys=False, allow_unicode=True)
    new = harness.load_policy(path)
    entry = ledger.append(f"human:{author}", "policy_change", {
        "old_version": old["version"], "old_hash": old["_hash"], "new_version": n, "new_hash": new["_hash"],
        "path": path.name, "author": author, "reason": reason}, db)
    signed = M.issue_policy(new, author, parent_hash=old["_hash"], db=db)
    return {"path": str(path), "hash": new["_hash"], "version": n, "ledger_idx": entry["idx"],
            "mandate_hash": signed["mandate_hash"]}
