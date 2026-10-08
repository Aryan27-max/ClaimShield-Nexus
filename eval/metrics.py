"""Evaluation metrics shared by checks, the Overview page and the results report.
Eval may read ground_truth / legit_outliers; core never imports this module."""
import pandas as pd

from core import harness
from core import predict as P
from core import schema as S
from core.snapshots import HORIZONS

HIGH = ["PREPAY_REVIEW", "FULL_INVESTIGATION", "REFER_TO_MFCU"]
COLS = harness.ACTIONS[::-1] + ["no_case"]
LEGIT = ["oncology", "busy_er", "honest_error"]
DEMO_THRESHOLDS = {"abstain.statistical_min": 0.40,  # Policy-page demo: E/M upcoding path, set live by a human
                   "actions.PREPAY_REVIEW.any_of.1.min_class_score.statistical": 0.55,
                   "actions.PREPAY_REVIEW.any_of.1.min_conf": 0.40}


def entity_labels() -> pd.DataFrame:
    gt = S.load("ground_truth").rename(columns={"scheme": "label"})[["entity_id", "label"]]
    lo = S.load("legit_outliers").rename(columns={"kind": "label"})[["entity_id", "label"]]
    lo["label"] = lo.label.replace({"high_cost_oncology": "oncology"})
    lab = pd.concat([gt, lo]).astype(str)
    p = S.load("providers").provider_id.astype(str)
    clean = pd.DataFrame({"entity_id": p[~p.isin(lab.entity_id)], "label": "clean"})
    return pd.concat([lab, clean], ignore_index=True)


def provider_actions(cases: pd.DataFrame) -> pd.DataFrame:
    return cases[["case_id", "providers", "recommended_action", "classes"]].explode("providers") \
        .rename(columns={"providers": "entity_id"})


def action_matrix(cases: pd.DataFrame, labels: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    lab = entity_labels() if labels is None else labels
    m = lab.merge(provider_actions(cases), on="entity_id", how="left")
    m["recommended_action"] = m.recommended_action.fillna("no_case")
    return pd.crosstab(m.label, m.recommended_action).reindex(columns=COLS, fill_value=0), m


def recall(cases: pd.DataFrame, labels: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per planted scheme: entities, share with any case, share at PREPAY_REVIEW or higher."""
    mat, _ = action_matrix(cases, labels)
    mat = mat.loc[[s for s in S.SCHEMES if s in mat.index]]
    n = mat.sum(axis=1)
    return pd.DataFrame({"scheme": mat.index, "entities": n.values,
                         "any_case": ((n - mat["no_case"]) / n).round(2).values,
                         "prepay_plus": (mat[HIGH].sum(axis=1) / n).round(2).values,
                         "prepay_plus_n": mat[HIGH].sum(axis=1).values})


def legit_outcomes(cases: pd.DataFrame, labels: pd.DataFrame | None = None) -> pd.DataFrame:
    mat, _ = action_matrix(cases, labels)
    mat = mat.loc[[x for x in LEGIT if x in mat.index]]
    return mat.loc[:, mat.sum() > 0]


def validation(cases: pd.DataFrame, labels: pd.DataFrame | None = None) -> dict:
    """Headline synthetic-validation numbers used by the Policy preview."""
    mat, m = action_matrix(cases, labels)
    clean = m[(m.label == "clean") & ~m.recommended_action.isin(harness.SAFE + ["no_case"])]
    legit_hi = int(mat.loc[[x for x in LEGIT if x in mat.index], ["FULL_INVESTIGATION", "REFER_TO_MFCU"]].sum().sum())
    return {"upcoding_prepay_plus": int(mat.loc["upcoding", HIGH].sum()),
            "planted_prepay_plus": int(mat.loc[[s for s in S.SCHEMES if s in mat.index], HIGH].sum().sum()),
            "clean_escalated": int(clean.entity_id.nunique()), "legit_full_or_mfcu": legit_hi}


def flag_rates(cases: pd.DataFrame, by: str, labels: pd.DataFrame | None = None) -> pd.DataFrame:
    """Share of providers recommended for investigator time (any non-safe action), per group, vs overall;
    `clean_rate` repeats it over clean providers only (false-positive rate)."""
    p = S.load("providers")[["provider_id", by]].astype(str).rename(columns={"provider_id": "entity_id"})
    pa = provider_actions(cases)
    hit = set(pa.entity_id[~pa.recommended_action.isin(harness.SAFE)])
    lab = (entity_labels() if labels is None else labels).set_index("entity_id").label
    p = p.assign(flag=p.entity_id.isin(hit), clean=p.entity_id.map(lab).eq("clean"))
    g = p.groupby(by).agg(providers=("flag", "size"), flagged=("flag", "sum"), flag_rate=("flag", "mean"))
    g["clean_rate"] = p[p.clean].groupby(by).flag.mean()
    g.attrs.update(overall=float(p.flag.mean()), overall_clean=float(p[p.clean].flag.mean()))
    return g.round(3).reset_index().sort_values("flag_rate", ascending=False)


def model_vs_baseline(snap: pd.DataFrame | None = None) -> pd.DataFrame:
    """Retrains each horizon and returns predict.compare rows (embargoed test split): model vs naive persistence
    baseline, on all rows and on new-onset rows. Same seed => same numbers as the pipeline's run_meta."""
    snap = pd.read_parquet(S.OUT / "snapshots.parquet") if snap is None else snap
    return pd.DataFrame([row for h in HORIZONS for row in P.train(snap, h)[2]["comparison"]])
