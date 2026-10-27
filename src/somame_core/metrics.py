"""Reporting that declines to fill in what it does not know.

Three rules, each of which exists because the obvious alternative is a
lie that looks like a number:

* **No completed work means no success rate**, not 0%. An agent that
  has done nothing has not failed at anything.
* **Hours returned require a baseline for every task counted**, and the
  baseline must be evidence — retrieved from a system of record, or
  stated by an accountable person. A model's guess at how long a human
  would have taken is not a measurement of anything.
* **Money requires a rate the customer stated.** Value, net return and
  return on cost are arithmetic on an internal hourly cost that only
  the customer knows. There is no default and no estimator, because an
  ROI figure built on a vendor-chosen rate is marketing, not reporting.

There are two ways in. :func:`summarise` takes individual task records.
:func:`summarise_totals` takes :class:`Totals` a host has already summed —
per-day rollups, typically — so a yearly report does not need a year of
rows in memory. Both apply the same rules, in the same function, so the
two can never disagree about what may be reported.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median as _median

from .provenance import DataOrigin, Sourced, Unavailable

__all__ = ["Report", "TaskRecord", "Totals", "summarise", "summarise_totals"]


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """One finished attempt.

    ``human_baseline_seconds`` is how long this task would have taken a
    person. It is a :class:`Sourced` rather than a float because where
    it came from decides whether it may be counted at all.
    """

    task_id: str
    agent_id: str
    succeeded: bool
    duration_seconds: float
    human_baseline_seconds: Sourced[float]

    @property
    def saved_seconds(self) -> float | None:
        base = self.human_baseline_seconds
        if not base.is_evidence or base.value is None:
            return None
        return max(0.0, base.value - self.duration_seconds)


@dataclass(frozen=True, slots=True)
class Totals:
    """A window's finished work, already summed.

    Every field is a count, or a sum of measured values. Nothing here can
    carry an estimate: a completed task without an evidential baseline is
    *counted* in ``completed_without_baseline`` and contributes nothing to
    ``saved_seconds``, which is what lets the hours-returned rule still be
    applied after the individual records are gone.

    Totals add, so a host can keep one per day and sum any window.
    """

    completed: int = 0
    failed: int = 0
    completed_seconds: float = 0.0
    """Sum of the durations of the completed tasks."""
    saved_seconds: float = 0.0
    """Sum of time saved over completed tasks that do have an evidential baseline."""
    completed_without_baseline: int = 0

    def __post_init__(self) -> None:
        for name in ("completed", "failed", "completed_without_baseline"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative.")
        if self.completed_seconds < 0 or self.saved_seconds < 0:
            raise ValueError("Durations cannot be negative.")
        if self.completed_without_baseline > self.completed:
            raise ValueError(
                "More completed tasks lack a baseline than were completed; "
                "the totals contradict each other."
            )

    @property
    def attempted(self) -> int:
        return self.completed + self.failed

    def __add__(self, other: Totals) -> Totals:
        return Totals(
            completed=self.completed + other.completed,
            failed=self.failed + other.failed,
            completed_seconds=self.completed_seconds + other.completed_seconds,
            saved_seconds=self.saved_seconds + other.saved_seconds,
            completed_without_baseline=(
                self.completed_without_baseline + other.completed_without_baseline
            ),
        )

    @classmethod
    def of(cls, records: Iterable[TaskRecord]) -> Totals:
        completed = failed = without = 0
        seconds = saved = 0.0
        for r in records:
            if not r.succeeded:
                failed += 1
                continue
            completed += 1
            seconds += r.duration_seconds
            if r.saved_seconds is None:
                without += 1
            else:
                saved += r.saved_seconds
        return cls(completed, failed, seconds, saved, without)

    @classmethod
    def sum(cls, parts: Iterable[Totals]) -> Totals:
        total = cls()
        for part in parts:
            total = total + part
        return total


@dataclass(frozen=True, slots=True)
class Report:
    """A period's figures, each carrying its own provenance."""

    completed: int
    failed: int
    success_rate: Sourced[float]
    mean_seconds: Sourced[float]
    median_seconds: Sourced[float]
    hours_returned: Sourced[float]
    value_returned: Sourced[float]
    net_return: Sourced[float]
    return_on_cost: Sourced[float]
    cost: Sourced[float]

    def as_lines(self) -> list[str]:
        """Human-readable, with every blank explained rather than zeroed."""
        rows = [
            ("Completed", str(self.completed)),
            ("Failed", str(self.failed)),
            ("Success rate", _pct(self.success_rate)),
            ("Mean task time", _secs(self.mean_seconds)),
            ("Median task time", _secs(self.median_seconds)),
            ("Hours returned", _num(self.hours_returned, "h")),
            ("Cost", _num(self.cost, "", prefix="$")),
            ("Value of hours returned", _num(self.value_returned, "", prefix="$")),
            ("Net return", _num(self.net_return, "", prefix="$")),
            ("Return on cost", _pct(self.return_on_cost)),
        ]
        width = max(len(label) for label, _ in rows)
        return [f"{label.ljust(width)}  {value}" for label, value in rows]


def _fmt_missing(s: Sourced[float]) -> str:
    return f"—  ({s.reason})"


def _pct(s: Sourced[float]) -> str:
    return f"{s.value * 100:.1f}%" if s.value is not None else _fmt_missing(s)


def _secs(s: Sourced[float]) -> str:
    if s.value is None:
        return _fmt_missing(s)
    v = s.value
    if v < 60:
        return f"{v:.0f}s"
    if v < 3600:
        return f"{v / 60:.1f}m"
    return f"{v / 3600:.1f}h"


def _num(s: Sourced[float], suffix: str, prefix: str = "") -> str:
    return f"{prefix}{s.value:,.1f}{suffix}" if s.value is not None else _fmt_missing(s)


def summarise(
    records: Sequence[TaskRecord],
    *,
    cost: Sourced[float] | None = None,
    hourly_rate: Sourced[float] | None = None,
    window_label: str = "window",
) -> Report:
    """Turn finished attempts into a report, leaving blanks where they belong.

    ``hourly_rate`` must be :data:`~somame_core.provenance.DataOrigin.USER_STATED`.
    A rate with any other origin is refused rather than used — that
    check is the whole point of threading provenance through to here.
    """
    durations = [r.duration_seconds for r in records if r.succeeded]
    if durations:
        med: Sourced[float] = Sourced(
            float(_median(durations)), DataOrigin.MEASURED, source="timer:task_duration"
        )
    else:
        med = Unavailable("No completed task has been timed.")
    return _report(Totals.of(records), med, cost, hourly_rate, window_label)


def summarise_totals(
    totals: Totals,
    *,
    cost: Sourced[float] | None = None,
    hourly_rate: Sourced[float] | None = None,
    window_label: str = "window",
) -> Report:
    """The same report, from totals a host has already summed.

    Identical to :func:`summarise` on the same work in every figure but
    one: the median, which cannot be recovered from sums and is reported
    as unavailable with that reason rather than approximated.
    """
    if totals.completed == 0:
        med: Sourced[float] = Unavailable("No completed task has been timed.")
    else:
        med = Unavailable(
            "A median needs every task's duration; this report was built from "
            "summed totals, so only the mean is known."
        )
    return _report(totals, med, cost, hourly_rate, window_label)


def _report(
    totals: Totals,
    median_seconds: Sourced[float],
    cost: Sourced[float] | None,
    hourly_rate: Sourced[float] | None,
    window_label: str,
) -> Report:
    """The rules. One implementation, whichever way the work arrived."""
    completed = totals.completed

    if totals.attempted == 0:
        rate: Sourced[float] = Unavailable(
            f"No attempts in this {window_label}; a success rate would be a claim about nothing."
        )
    else:
        rate = Sourced(
            completed / totals.attempted, DataOrigin.MEASURED, source=f"tasks:{window_label}"
        )

    if completed == 0:
        mean: Sourced[float] = Unavailable("No completed task has been timed.")
    else:
        mean = Sourced(
            totals.completed_seconds / completed, DataOrigin.MEASURED, source="timer:task_duration"
        )

    # Hours returned are all-or-nothing on purpose. Summing only the
    # tasks that happen to have a baseline would understate the total
    # while looking like the total, which is worse than saying so.
    without = totals.completed_without_baseline
    if completed == 0:
        hours: Sourced[float] = Unavailable("Nothing has been completed yet.")
    elif without:
        hours = Unavailable(
            f"{without} of {completed} completed tasks have no human baseline on record "
            "from a named source, so the total would be an undercount presented as a total."
        )
    else:
        hours = Sourced(
            totals.saved_seconds / 3600.0, DataOrigin.MEASURED, source="baseline:per_task"
        )

    known_cost = cost or Unavailable("No cost recorded for this window.")

    if hourly_rate is None or hourly_rate.value is None:
        no_rate = "No internal hourly cost has been stated, and we will not pick one."
        value: Sourced[float] = Unavailable(no_rate)
    elif hourly_rate.origin is not DataOrigin.USER_STATED:
        refused = (
            f"The hourly cost on file has origin {hourly_rate.origin.value}; only a rate stated "
            "by an accountable person may be used for money figures."
        )
        value = Unavailable(refused)
    elif hours.value is None:
        value = Unavailable(f"Hours returned are unavailable: {hours.reason}")
    else:
        value = Sourced(
            hours.value * hourly_rate.value,
            DataOrigin.USER_STATED,
            source=f"rate:{hourly_rate.source}",
        )

    if value.value is None:
        net: Sourced[float] = Unavailable(value.reason or "Value is unavailable.")
        roi: Sourced[float] = Unavailable(value.reason or "Value is unavailable.")
    elif known_cost.value is None:
        net = Unavailable(known_cost.reason or "Cost is unavailable.")
        roi = Unavailable(known_cost.reason or "Cost is unavailable.")
    else:
        net = Sourced(value.value - known_cost.value, DataOrigin.USER_STATED, source=value.source)
        if known_cost.value == 0:
            roi = Unavailable("Cost is zero, so return on cost is undefined rather than infinite.")
        else:
            roi = Sourced(
                (value.value - known_cost.value) / known_cost.value,
                DataOrigin.USER_STATED,
                source=value.source,
            )

    return Report(
        completed=completed,
        failed=totals.failed,
        success_rate=rate,
        mean_seconds=mean,
        median_seconds=median_seconds,
        hours_returned=hours,
        value_returned=value,
        net_return=net,
        return_on_cost=roi,
        cost=known_cost,
    )
