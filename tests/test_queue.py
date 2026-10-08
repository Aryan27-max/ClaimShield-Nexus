"""Capacity queue invariants on the real pipeline output."""
import pandas as pd
import pytest

from core import harness
from core import queue as Q
from core import schema as S

pytestmark = pytest.mark.skipif(not S.CASES.exists(), reason="run python -m core.pipeline first")
STATUSES = {"in_capacity", "over_capacity", "deferred", "not_queued"}


@pytest.fixture(scope="module")
def ev():
    pol = harness.load_policy()
    return harness.evaluate_all(pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS), pol), pol


@pytest.mark.parametrize("n", range(1, 11))
def test_every_investigator_count_keeps_every_case(ev, n):
    cases, pol = ev
    q = Q.rank(cases, pol, investigators=n)
    assert len(q) == len(cases) and set(q.case_id) == set(cases.case_id) and q.case_id.is_unique
    assert set(q.status) <= STATUSES and list(q["rank"]) == list(range(1, len(q) + 1))
    used = q.est_hours[q.status == "in_capacity"].sum()
    assert used == pytest.approx(q.attrs["used_hours"]) and used <= n * pol["capacity"]["hours_per_investigator_week"]
    assert q.attrs["weeks_to_clear"] == round(q.est_hours[q.queued].sum() / q.attrs["capacity_hours"], 1)


def test_monitor_and_needs_data_use_no_capacity(ev):
    cases, pol = ev
    q = Q.rank(cases, pol)
    safe = q.recommended_action.isin(pol["capacity"]["no_capacity_actions"])
    assert (q.status[safe] == "not_queued").all() and (q.est_hours[safe] == 0).all()
    assert (q.status[~safe] != "not_queued").all()


def test_more_investigators_only_displace_for_higher_priority(ev):
    """Must-take first means a small backfill case can lose its slot when a higher-ranked case now fits.
    It is never dropped: it stays listed as deferred, and only a higher-ranked newcomer can displace it."""
    cases, pol = ev
    prev, prev_mt = None, 0
    for n in range(1, 11):
        q = Q.rank(cases, pol, investigators=n).set_index("case_id")
        slate = set(q.index[q.status == "in_capacity"])
        n_mt = int((q.must_take & (q.status == "in_capacity")).sum())
        assert n_mt >= prev_mt
        if prev is not None:
            entered = slate - prev
            for x in prev - slate:
                assert q.at[x, "status"] in {"deferred", "over_capacity"}
                assert any(q.at[y, "rank"] < q.at[x, "rank"] for y in entered), (n, x)
        prev, prev_mt = slate, n_mt


def test_must_take_ranked_first_by_priority(ev):
    cases, pol = ev
    q = Q.rank(cases, pol)
    mt_rule = pol["must_take"]
    expect = q.queued & (q.recommended_action.isin(mt_rule["actions"]) | (q.max_severity >= mt_rule["min_severity"]))
    assert (q.must_take == expect).all() and q.must_take.any()
    queued = q[q.queued]
    first_non = queued.must_take.values.argmin()
    assert queued.must_take.values[:first_non].all() and not queued.must_take.values[first_non:].any()
    assert queued.priority[queued.must_take].is_monotonic_decreasing
    assert (q.status[q.status == "over_capacity"].index.isin(q.index[q.must_take])).all()
    assert not (q.must_take & (q.status == "deferred")).any()


@pytest.mark.parametrize("h", [30, 60, 90])
def test_horizon_switches_p_fwa_source(ev, h):
    cases, pol = ev
    q = Q.rank(cases, pol, horizon=h)
    expected = q[f"p_{h}"].astype(float).fillna(q.confidence.astype(float))
    pd.testing.assert_series_equal(q.p_fwa, expected, check_names=False)
    assert q.attrs["horizon"] == h


def test_horizons_rank_differently(ev):
    cases, pol = ev
    p = {h: Q.rank(cases, pol, horizon=h).set_index("case_id").p_fwa.sort_index() for h in (30, 90)}
    assert not p[30].equals(p[90])
