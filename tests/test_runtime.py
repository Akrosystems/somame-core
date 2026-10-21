"""A tool cannot be reached except through the gate."""

from __future__ import annotations

import pytest

from somame_core.gate import ActionClass, Reversibility, SupervisionLevel
from somame_core.runtime import (
    DenyAll,
    Intent,
    Runner,
    Tool,
    ToolNotRegistered,
)


class Spy:
    """Records calls, so a test can assert a side effect did not happen."""

    def __init__(self):
        self.calls: list[dict] = []
        self.undone: list[dict] = []

    def __call__(self, args):
        self.calls.append(dict(args))
        return {"ok": True}

    def undo(self, args, _result):
        self.undone.append(dict(args))


@pytest.fixture
def spy():
    return Spy()


def deleter(spy):
    return Tool("delete_row", ActionClass.DELETE, Reversibility.REVERSIBLE, spy, undo=spy.undo)


def updater(spy):
    return Tool("set_field", ActionClass.UPDATE, Reversibility.REVERSIBLE, spy, undo=spy.undo)


def reader(spy):
    return Tool("read_rows", ActionClass.READ, Reversibility.COSTLY, spy)


def test_a_held_deletion_never_reaches_the_tool(spy):
    """The behavioural claim, not just the decision object."""
    r = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, [deleter(spy)])
    out = r.submit(Intent("delete_row", {"row": 1}, target="settlements/1"))
    assert not out.ran
    assert out.held
    assert spy.calls == []           # the function was never called
    assert len(r.held) == 1


def test_a_rejected_action_never_reaches_the_tool(spy):
    r = Runner("a1", SupervisionLevel.APPROVE_EVERY_WRITE, [updater(spy)], approver=DenyAll())
    out = r.submit(Intent("set_field", {"x": 1}))
    assert not out.ran
    assert spy.calls == []


def test_an_approved_action_runs_and_records_who(spy):
    r = Runner("a1", SupervisionLevel.APPROVE_EVERY_WRITE, [updater(spy)],
               approver=lambda i, d: (True, "robert"))
    out = r.submit(Intent("set_field", {"x": 1}))
    assert out.ran
    assert out.approved_by == "robert"
    assert spy.calls == [{"x": 1}]


def test_reads_run_without_an_approver(spy):
    r = Runner("a1", SupervisionLevel.READ_ONLY, [reader(spy)])
    assert r.submit(Intent("read_rows")).ran


def test_level_zero_blocks_a_write_even_with_a_willing_approver(spy):
    r = Runner("a1", SupervisionLevel.READ_ONLY, [updater(spy)],
               approver=lambda i, d: (True, "robert"))
    out = r.submit(Intent("set_field", {"x": 1}))
    assert out.decision.blocked
    assert not out.ran
    assert spy.calls == []


def test_an_unregistered_tool_raises(spy):
    r = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, [reader(spy)])
    with pytest.raises(ToolNotRegistered):
        r.submit(Intent("delete_row"))


def test_every_submission_is_audited_whatever_the_outcome(spy):
    r = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, [deleter(spy), reader(spy)])
    r.submit(Intent("read_rows"))
    r.submit(Intent("delete_row", {"row": 1}))
    kinds = [e.kind for e in r.log]
    assert kinds.count("decision") == 2
    r.log.verify()


def test_a_failing_tool_is_reported_not_swallowed():
    def boom(_args):
        raise RuntimeError("source dataset is locked")

    tool = Tool("extract", ActionClass.EXECUTE, Reversibility.COSTLY, boom)
    r = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, [tool])
    out = r.submit(Intent("extract"))
    assert not out.ran
    assert out.error == "source dataset is locked"
    assert any(e.kind == "error" for e in r.log)


def test_duration_is_measured_not_estimated(spy):
    r = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, [updater(spy)])
    out = r.submit(Intent("set_field", {"x": 1}))
    assert out.duration is not None
    assert out.duration.origin.value == "measured"
    assert out.duration.is_evidence


def test_undo_reverses_and_is_logged(spy):
    r = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, [updater(spy)])
    out = r.submit(Intent("set_field", {"x": 1}))
    assert r.undo(out) is True
    assert spy.undone == [{"x": 1}]
    assert any(e.kind == "undo" for e in r.log)


def test_undo_returns_false_rather_than_raising_when_impossible():
    tool = Tool("send_email", ActionClass.PUBLISH_EXTERNAL, Reversibility.IRREVERSIBLE,
                lambda a: {"sent": True})
    r = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, [tool],
               approver=lambda i, d: (True, "robert"))
    out = r.submit(Intent("send_email", {"to": "x@y.z"}))
    assert out.ran
    assert r.undo(out) is False


def test_a_tool_claiming_reversible_must_supply_an_undo():
    with pytest.raises(ValueError, match="no undo"):
        Tool("x", ActionClass.UPDATE, Reversibility.REVERSIBLE, lambda a: None)


def test_the_default_approver_holds_rather_than_proceeds(spy):
    """A runner built without an approver must not become permissive."""
    r = Runner("a1", SupervisionLevel.APPROVE_EVERY_WRITE, [updater(spy)])
    assert not r.submit(Intent("set_field", {"x": 1})).ran
    assert spy.calls == []
