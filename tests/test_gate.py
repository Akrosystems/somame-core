"""The gate's promise, written as tests rather than as documentation."""

from __future__ import annotations

import itertools

import pytest

from somame_core.gate import (
    MANDATORY_ESCALATIONS,
    ActionClass,
    GateError,
    Reversibility,
    SupervisionLevel,
    decide,
    requires_human,
)


@pytest.mark.parametrize("action", sorted(MANDATORY_ESCALATIONS, key=lambda a: a.value))
@pytest.mark.parametrize("rev", list(Reversibility))
@pytest.mark.parametrize("level", list(SupervisionLevel))
def test_mandatory_classes_always_reach_a_human(action, rev, level):
    """The central claim. If this ever passes at L3, the product is broken."""
    if level is SupervisionLevel.READ_ONLY:
        # At level 0 it does not reach a human either — it cannot run at all.
        assert decide(action, rev, level).blocked
        return
    assert requires_human(action, rev, level) is True
    d = decide(action, rev, level)
    assert d.needs_human and not d.allowed


def test_autonomous_still_escalates_deletion():
    """Stated separately because it is the case people assume is exempt."""
    d = decide(
        ActionClass.DELETE,
        Reversibility.REVERSIBLE,
        SupervisionLevel.AUTONOMOUS_AUDITED,
        target="settlements",
    )
    assert d.needs_human
    assert d.rule == "mandatory"
    assert "no setting can switch it off" in d.reason


def test_irreversible_always_reaches_a_human_even_outside_the_mandatory_set():
    for action in ActionClass:
        if action in MANDATORY_ESCALATIONS or action in (ActionClass.READ, ActionClass.DRAFT):
            continue
        assert requires_human(
            action, Reversibility.IRREVERSIBLE, SupervisionLevel.AUTONOMOUS_AUDITED
        )


def test_reads_and_drafts_never_need_approval():
    for action in (ActionClass.READ, ActionClass.DRAFT):
        for rev, level in itertools.product(Reversibility, SupervisionLevel):
            assert requires_human(action, rev, level) is False
            assert decide(action, rev, level).allowed


def test_level_zero_blocks_rather_than_queues():
    """A blocked action is not an approval waiting to happen."""
    d = decide(ActionClass.UPDATE, Reversibility.REVERSIBLE, SupervisionLevel.READ_ONLY)
    assert d.blocked
    assert not d.needs_human  # nobody can approve it into running
    assert not d.allowed


def test_routine_reversible_work_runs_at_level_two_and_three():
    for level in (SupervisionLevel.NOTIFY_AND_UNDO, SupervisionLevel.AUTONOMOUS_AUDITED):
        d = decide(ActionClass.UPDATE, Reversibility.REVERSIBLE, level)
        assert d.allowed and not d.needs_human


def test_level_two_demands_an_undo_payload():
    d = decide(ActionClass.UPDATE, Reversibility.REVERSIBLE, SupervisionLevel.NOTIFY_AND_UNDO)
    assert d.undo_required


def test_plain_integers_are_accepted_as_levels():
    """Callers read levels out of database columns; do not make them coerce."""
    assert requires_human(ActionClass.UPDATE, Reversibility.REVERSIBLE, 1) is True
    assert requires_human(ActionClass.UPDATE, Reversibility.REVERSIBLE, 3) is False


def test_mandatory_set_is_immutable():
    """A settings row could be edited at runtime. A frozenset constant cannot."""
    assert isinstance(MANDATORY_ESCALATIONS, frozenset)
    with pytest.raises(AttributeError):
        MANDATORY_ESCALATIONS.add(ActionClass.UPDATE)  # type: ignore[attr-defined]


def test_mandatory_set_has_not_shrunk():
    """Names the four explicitly, so removing one fails here and not in production."""
    assert {
        ActionClass.DELETE,
        ActionClass.MOVE_MONEY,
        ActionClass.PUBLISH_EXTERNAL,
        ActionClass.CHANGE_ACCESS,
    } == MANDATORY_ESCALATIONS


def test_decision_require_raises_when_not_cleared():
    d = decide(ActionClass.DELETE, Reversibility.REVERSIBLE, SupervisionLevel.AUTONOMOUS_AUDITED)
    with pytest.raises(GateError):
        d.require()


def test_reason_names_the_target():
    d = decide(
        ActionClass.MOVE_MONEY,
        Reversibility.IRREVERSIBLE,
        SupervisionLevel.APPROVE_EVERY_WRITE,
        target="GHS 31,480 to supplier 8821",
    )
    assert "GHS 31,480 to supplier 8821" in d.reason
