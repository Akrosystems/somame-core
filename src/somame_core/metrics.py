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
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median as _median

from .provenance import DataOrigin, Sourced, Unavailable

__all__ = ["Report", "TaskRecord", "summarise"]


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
    attempted = len(records)
    done = [r for r in records if r.succeeded]
    completed = len(done)
    failed = attempted - completed

    if attempted == 0:
        rate: Sourced[float] = Unavailable(
            f"No attempts in this {window_label}; a success rate would be a claim about nothing."
        )
    else:
        rate = Sourced(completed / attempted, DataOrigin.MEASURED, source=f"tasks:{window_label}")

    if completed == 0:
        mean: Sourced[float] = Unavailable("No completed task has been timed.")
        med: Sourced[float] = Unavailable("No completed task has been timed.")
    else:
        durations = [r.duration_seconds for r in done]
        mean = Sourced(sum(durations) / completed, DataOrigin.MEASURED, source="timer:task_duration")
        med = Sourced(float(_median(durations)), DataOrigin.MEASURED, source="timer:task_duration")

    # Hours returned are all-or-nothing on purpose. Summing only the
    # tasks that happen to have a baseline would understate the total
    # while looking like the total, which is worse than saying so.
    without = [r for r in done if r.saved_seconds is None]
    if completed == 0:
        hours: Sourced[float] = Unavailable("Nothing has been completed yet.")
    elif without:
        hours = Unavailable(
            f"{len(without)} of {completed} completed tasks have no human baseline on record "
            "from a named source, so the total would be an undercount presented as a total."
        )
    else:
        total = sum(r.saved_seconds or 0.0 for r in done)
        hours = Sourced(total / 3600.0, DataOrigin.MEASURED, source="baseline:per_task")

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
        failed=failed,
        success_rate=rate,
        mean_seconds=mean,
        median_seconds=med,
        hours_returned=hours,
        value_returned=value,
        net_return=net,
        return_on_cost=roi,
        cost=known_cost,
    )
