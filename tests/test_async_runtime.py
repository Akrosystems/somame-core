"""The asynchronous runner makes exactly the decisions the synchronous one does."""

from __future__ import annotations

import asyncio

from somame_core.gate import ActionClass, Reversibility, SupervisionLevel
from somame_core.runtime import AsyncRunner, Intent, Runner, Tool


def _tools(calls: list[str]) -> list[Tool]:
    async def delete(args):
        calls.append(f"delete:{args['row']}")
        return {"deleted": args["row"]}

    async def restore(args, _result):
        calls.append(f"restore:{args['row']}")

    async def read(_args):
        calls.append("read")
        return {"rows": 3}

    return [
        Tool("delete_row", ActionClass.DELETE, Reversibility.REVERSIBLE, delete, undo=restore),
        Tool("read_rows", ActionClass.READ, Reversibility.REVERSIBLE, read),
    ]


def test_a_held_deletion_never_reaches_an_async_tool():
    calls: list[str] = []
    runner = AsyncRunner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, _tools(calls))
    out = asyncio.run(runner.submit(Intent("delete_row", {"row": 1})))
    assert out.held and not out.ran
    assert calls == []


def test_an_async_approver_can_release_it_and_undo_reverses_it():
    calls: list[str] = []

    async def approve(_intent, _decision):
        return (True, "robert")

    runner = AsyncRunner(
        "a1", SupervisionLevel.APPROVE_EVERY_WRITE, _tools(calls), approver=approve
    )

    async def scenario():
        out = await runner.submit(Intent("delete_row", {"row": 7}))
        assert out.ran and out.approved_by == "robert"
        assert await runner.undo(out) is True

    asyncio.run(scenario())
    assert calls == ["delete:7", "restore:7"]
    runner.log.verify()


def test_both_runners_write_the_same_audit_kinds_for_the_same_intents():
    sync_calls: list[str] = []
    sync_tools = [
        Tool(
            "delete_row",
            ActionClass.DELETE,
            Reversibility.REVERSIBLE,
            lambda a: sync_calls.append("d"),
            undo=lambda a, r: None,
        ),
        Tool("read_rows", ActionClass.READ, Reversibility.REVERSIBLE, lambda a: {"rows": 3}),
    ]
    sync = Runner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, sync_tools)
    async_runner = AsyncRunner("a1", SupervisionLevel.AUTONOMOUS_AUDITED, _tools([]))
    intents = [Intent("read_rows"), Intent("delete_row", {"row": 1})]

    for intent in intents:
        sync.submit(intent)

    async def run_async():
        for intent in intents:
            await async_runner.submit(intent)

    asyncio.run(run_async())
    assert [e.kind for e in sync.log] == [e.kind for e in async_runner.log]
    assert [e.summary for e in sync.log] == [e.summary for e in async_runner.log]
