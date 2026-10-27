"""`somame-core` — check the gate, and the honesty rules, from a terminal.

Three subcommands, each answering a question someone evaluating Somame
would reasonably ask before trusting it:

    somame-core gate          What needs a human, at every level?
    somame-core demo          Show a run where the gate actually stops something.
    somame-core verify        Does this audit chain reproduce?
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .audit import AuditLog, TamperDetected
from .gate import ActionClass, Reversibility, SupervisionLevel, decide
from .metrics import TaskRecord, summarise
from .provenance import DataOrigin, Sourced, Unavailable, check_no_fabrication_member
from .runtime import Intent, Runner, Tool


def _gate_table(_: argparse.Namespace) -> int:
    """Print the whole decision surface. No surprises hidden in a branch."""
    levels = list(SupervisionLevel)
    header = (
        "action".ljust(18)
        + "reversibility".ljust(16)
        + "".join(f"L{int(lv)}".ljust(10) for lv in levels)
    )
    print(header)
    print("-" * len(header))
    for action in ActionClass:
        for rev in Reversibility:
            row = action.value.ljust(18) + rev.value.ljust(16)
            for level in levels:
                d = decide(action, rev, level)
                mark = "blocked" if d.blocked else ("human" if d.needs_human else "auto")
                row += mark.ljust(10)
            print(row)
    print()
    print("'human' means a person must approve before it runs.")
    print("'blocked' means it cannot run at all and cannot be approved into running.")
    print("Note that the four mandatory classes read 'human' at every level, including L3.")
    return 0


def _demo(_: argparse.Namespace) -> int:
    """A short run in which an agent tries to delete something."""
    deleted: list[str] = []

    def do_delete(args: Mapping[str, Any]) -> dict[str, Any]:
        deleted.append(str(args["row"]))
        return {"deleted": args["row"]}

    def undo_delete(args: Mapping[str, Any], _result: Any) -> None:
        deleted.remove(str(args["row"]))

    def do_read(_args: Mapping[str, Any]) -> dict[str, Any]:
        return {"rows": 14}

    tools = [
        Tool("count_duplicates", ActionClass.READ, Reversibility.REVERSIBLE, do_read),
        Tool(
            "delete_row", ActionClass.DELETE, Reversibility.REVERSIBLE, do_delete, undo=undo_delete
        ),
    ]

    # Level 3 is the most permissive setting Somame offers.
    runner = Runner("demo-agent", SupervisionLevel.AUTONOMOUS_AUDITED, tools)

    print("Agent is on AUTONOMOUS_AUDITED (level 3), the most permissive setting.\n")

    first = runner.submit(Intent("count_duplicates", target="settlements"))
    print(f"  count_duplicates  ran={first.ran}  {first.decision.reason}")

    second = runner.submit(
        Intent("delete_row", {"row": "settlement:8821"}, target="settlements/8821")
    )
    print(f"  delete_row        ran={second.ran}  {second.decision.reason}")
    print(f"\n  Rows actually deleted: {len(deleted)}")
    print(f"  Intents held for a person: {len(runner.held)}")
    print(f"  Audit entries written: {len(runner.log)}")
    runner.log.verify()
    print("  Audit chain verifies.\n")

    # And the reporting half: a rate nobody stated produces no ROI.
    records = [
        TaskRecord(
            "t1",
            "demo-agent",
            True,
            412.0,
            Sourced(3600.0, DataOrigin.RETRIEVED, source="timesheet:2026-09"),
        ),
        TaskRecord(
            "t2", "demo-agent", True, 890.0, Unavailable("No baseline recorded for this task.")
        ),
    ]
    print("Reporting over 2 completed tasks, one without a human baseline:\n")
    for line in summarise(records, window_label="demo").as_lines():
        print("  " + line)
    print()
    check_no_fabrication_member()
    print("DataOrigin carries no label for fabricated data.")
    return 0


def _verify(ns: argparse.Namespace) -> int:
    path = Path(ns.path)
    if not path.exists():
        print(f"No such file: {path}", file=sys.stderr)
        return 2
    log = AuditLog.from_jsonl(path.read_text(encoding="utf-8"))
    try:
        log.verify()
    except TamperDetected as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"{len(log)} entries verify. Head is {log.head[:16]}…")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="somame-core",
        description="The supervised agent runtime behind Somame. MIT licensed.",
    )
    subs = parser.add_subparsers(dest="cmd", required=True)

    subs.add_parser("gate", help="Print the full decision table.").set_defaults(fn=_gate_table)
    subs.add_parser("demo", help="Run an agent that tries to delete something.").set_defaults(
        fn=_demo
    )

    v = subs.add_parser("verify", help="Verify an exported audit chain (JSONL).")
    v.add_argument("path")
    v.set_defaults(fn=_verify)

    ns = parser.parse_args(argv)
    return int(ns.fn(ns))


if __name__ == "__main__":
    raise SystemExit(main())
