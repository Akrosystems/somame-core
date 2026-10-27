"""Reporting refuses to fill in what it was not told."""

from __future__ import annotations

import pytest

from somame_core.metrics import TaskRecord, Totals, summarise, summarise_totals
from somame_core.provenance import DataOrigin, Sourced, Unavailable

BASE = Sourced(3600.0, DataOrigin.RETRIEVED, source="timesheet:2026-09")
RATE = Sourced(45.0, DataOrigin.USER_STATED, source="director:hourly_cost")
COST = Sourced(420.0, DataOrigin.MEASURED, source="billing:period")


def done(tid="t1", dur=600.0, base=BASE):
    return TaskRecord(tid, "a1", True, dur, base)


def test_no_work_means_no_success_rate_not_zero():
    r = summarise([])
    assert r.success_rate.value is None
    assert "nothing" in (r.success_rate.reason or "").lower()


def test_success_rate_is_measured_when_there_is_work():
    r = summarise([done("t1"), TaskRecord("t2", "a1", False, 10.0, BASE)])
    assert r.success_rate.value == 0.5
    assert r.success_rate.origin is DataOrigin.MEASURED


def test_hours_returned_need_a_baseline_for_every_counted_task():
    """One missing baseline blanks the total rather than understating it."""
    r = summarise([done("t1"), done("t2", base=Unavailable("none recorded"))])
    assert r.hours_returned.value is None
    assert "1 of 2" in (r.hours_returned.reason or "")


def test_hours_returned_computed_when_every_task_has_one():
    r = summarise([done("t1", 600.0), done("t2", 600.0)])
    assert r.hours_returned.value == (3000.0 + 3000.0) / 3600.0


def test_a_model_guess_is_not_an_acceptable_baseline():
    guess = Sourced(3600.0, DataOrigin.MODEL_GEN, source="model:estimate")
    r = summarise([done("t1", base=guess)])
    assert r.hours_returned.value is None


def test_a_task_slower_than_the_human_never_returns_negative_hours():
    slow = TaskRecord("t1", "a1", True, 7200.0, BASE)
    assert slow.saved_seconds == 0.0


def test_no_rate_means_no_value_no_net_and_no_roi():
    r = summarise([done()], cost=COST)
    for field in (r.value_returned, r.net_return, r.return_on_cost):
        assert field.value is None
        assert "will not pick one" in (field.reason or "")


def test_a_rate_we_inferred_rather_than_were_told_is_refused():
    """Only a person may state what an hour of their people's time costs."""
    inferred = Sourced(45.0, DataOrigin.MODEL_GEN, source="model:guess")
    r = summarise([done()], cost=COST, hourly_rate=inferred)
    assert r.value_returned.value is None
    assert "accountable person" in (r.value_returned.reason or "")


def test_a_retrieved_rate_is_also_refused():
    retrieved = Sourced(45.0, DataOrigin.RETRIEVED, source="hris:avg_salary")
    r = summarise([done()], cost=COST, hourly_rate=retrieved)
    assert r.value_returned.value is None


def test_money_is_computed_once_a_rate_is_stated():
    r = summarise([done("t1", 600.0)], cost=COST, hourly_rate=RATE)
    saved_h = 3000.0 / 3600.0
    assert r.value_returned.value == saved_h * 45.0
    assert r.net_return.value == r.value_returned.value - 420.0
    assert r.return_on_cost.value == (r.value_returned.value - 420.0) / 420.0


def test_zero_cost_gives_undefined_roi_not_infinity():
    free = Sourced(0.0, DataOrigin.MEASURED, source="billing:trial")
    r = summarise([done()], cost=free, hourly_rate=RATE)
    assert r.return_on_cost.value is None
    assert "undefined" in (r.return_on_cost.reason or "")


def test_unknown_cost_blanks_net_and_roi_but_keeps_value():
    r = summarise([done()], hourly_rate=RATE)
    assert r.value_returned.value is not None
    assert r.net_return.value is None
    assert r.return_on_cost.value is None


def test_every_blank_line_carries_its_reason():
    lines = summarise([]).as_lines()
    for line in lines:
        if "—" in line:
            assert "(" in line and ")" in line


# --- summarise_totals: the same rules from summed work ---------------------


def test_totals_report_matches_the_record_report_except_the_median():
    records = [done("t1", 600.0), done("t2", 900.0), TaskRecord("t3", "a1", False, 30.0, BASE)]
    by_record = summarise(records, cost=COST, hourly_rate=RATE)
    by_totals = summarise_totals(Totals.of(records), cost=COST, hourly_rate=RATE)
    for field in (
        "success_rate",
        "mean_seconds",
        "hours_returned",
        "value_returned",
        "net_return",
        "return_on_cost",
    ):
        assert getattr(by_totals, field).value == getattr(by_record, field).value, field
    assert by_record.median_seconds.value is not None
    assert by_totals.median_seconds.value is None
    assert "summed totals" in (by_totals.median_seconds.reason or "")


def test_daily_totals_add_into_the_window():
    day1 = Totals.of([done("t1", 600.0)])
    day2 = Totals.of([done("t2", 600.0, base=Unavailable("none"))])
    week = Totals.sum([day1, day2])
    assert (week.completed, week.completed_without_baseline) == (2, 1)
    # One day without a baseline blanks the whole window, as with records.
    assert summarise_totals(week).hours_returned.value is None


def test_no_totals_means_no_rate_and_no_median():
    r = summarise_totals(Totals())
    assert r.success_rate.value is None
    assert r.median_seconds.value is None
    assert "nothing" in (r.success_rate.reason or "").lower()


def test_totals_that_contradict_themselves_are_refused():
    with pytest.raises(ValueError, match="contradict"):
        Totals(completed=1, completed_without_baseline=2)
    with pytest.raises(ValueError):
        Totals(failed=-1)
