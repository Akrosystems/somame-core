"""The supervised run loop: a tool call cannot bypass the gate.

The arrangement matters more than the code. A runtime where the agent
calls tools directly and the gate is something the tool is supposed to
consult has already lost: every new tool is a new chance to forget. So
here the agent never holds a tool. It returns an intent; the runner
classifies it, puts it through :mod:`somame_core.gate`, and only then —
if the gate clears it, or a human approves it — invokes the tool.

A :class:`Tool` therefore declares what it does (``action``,
``reversibility``) as part of its identity, and the runner trusts that
declaration the way it trusts a type signature. Registering a tool that
deletes rows while declaring itself a ``READ`` is the one way through,
and it is a deliberate act visible in a diff.

Two runners share one implementation of the decision path:
:class:`Runner` for synchronous hosts and :class:`AsyncRunner` for hosts
whose tools and approval inbox live on an event loop.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .audit import AuditLog
from .gate import INERT_ACTIONS, ActionClass, Decision, Reversibility, SupervisionLevel, decide
from .provenance import DataOrigin, Sourced

__all__ = [
    "AlwaysAsk",
    "Approver",
    "AsyncApprover",
    "AsyncRunner",
    "DenyAll",
    "Intent",
    "Outcome",
    "Runner",
    "Tool",
    "ToolNotRegistered",
]


class ToolNotRegistered(KeyError):
    """The agent asked for a tool the runner does not have."""


@dataclass(frozen=True, slots=True)
class Tool:
    """A capability, with its effect on the world declared up front.

    ``run`` and ``undo`` may be plain functions or, under
    :class:`AsyncRunner`, coroutine functions.
    """

    name: str
    action: ActionClass
    reversibility: Reversibility
    run: Callable[[Mapping[str, Any]], Any]
    description: str = ""
    undo: Callable[[Mapping[str, Any], Any], Any] | None = None
    """Given the original arguments and the result, put things back."""

    def __post_init__(self) -> None:
        # A read or a draft changes nothing, so there is nothing to put back.
        if self.action in INERT_ACTIONS:
            return
        if self.reversibility is Reversibility.REVERSIBLE and self.undo is None:
            raise ValueError(
                f"Tool {self.name!r} claims to be reversible but provides no undo. "
                "Either supply one or declare it COSTLY."
            )


@dataclass(frozen=True, slots=True)
class Intent:
    """What the agent wants to do next. It is a request, not an action."""

    tool: str
    args: Mapping[str, Any] = field(default_factory=dict)
    target: str | None = None
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happened to one intent."""

    intent: Intent
    decision: Decision
    ran: bool
    result: Any = None
    error: str | None = None
    duration: Sourced[float] | None = None
    approved_by: str | None = None
    """Who approved it, when a person did."""
    rejected_by: str | None = None
    """Who refused it, when a person did. A rejection is an answer, not a hold."""

    @property
    def held(self) -> bool:
        """True when the gate stopped it and no person has answered yet."""
        return not self.ran and self.error is None and self.rejected_by is None

    @property
    def rejected(self) -> bool:
        return self.rejected_by is not None


class Approver(Protocol):
    """How a human decision reaches the runner.

    A real deployment implements this against its approval inbox: the
    call blocks, or the run suspends and resumes. The two included
    implementations are for tests and for dry runs.
    """

    def __call__(self, intent: Intent, decision: Decision) -> tuple[bool, str] | None:
        """Return ``(approved, who)``, or ``None`` to leave it held."""


class AsyncApprover(Protocol):
    """An :class:`Approver` for hosts whose approval inbox is asynchronous."""

    async def __call__(self, intent: Intent, decision: Decision) -> tuple[bool, str] | None:
        """Return ``(approved, who)``, or ``None`` to leave it held."""


class AlwaysAsk:
    """An approver that holds everything. The default, and the honest one.

    A runner constructed without an approver does not quietly proceed;
    it collects held intents and hands them back for a person.
    """

    def __call__(self, intent: Intent, decision: Decision) -> tuple[bool, str] | None:
        return None


class DenyAll:
    """Rejects everything that needs a human. Useful for testing the gate."""

    def __call__(self, intent: Intent, decision: Decision) -> tuple[bool, str] | None:
        return (False, "policy:deny_all")


class _Supervisor:
    """What both runners share: the gate, the audit entries, the outcomes.

    The two public runners differ only in whether they await the approver
    and the tool. Everything that decides or records lives here, once, so
    the synchronous and asynchronous paths cannot drift apart.
    """

    def __init__(
        self,
        agent_id: str,
        supervision: SupervisionLevel | int,
        tools: list[Tool] | None = None,
        *,
        log: AuditLog | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.supervision = SupervisionLevel(int(supervision))
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or [])}
        self.log = log or AuditLog()
        self.held: list[Outcome] = []

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def _gate(self, intent: Intent) -> tuple[Tool, Decision]:
        tool = self.tools.get(intent.tool)
        if tool is None:
            raise ToolNotRegistered(
                f"{intent.tool!r} is not registered for {self.agent_id}. "
                "An agent cannot reach a capability it was not given."
            )
        decision = decide(
            tool.action,
            tool.reversibility,
            self.supervision,
            target=intent.target or tool.name,
        )
        self.log.append(
            actor=f"agent:{self.agent_id}",
            kind="decision",
            summary=decision.reason,
            detail={
                "tool": tool.name,
                "action": tool.action.value,
                "reversibility": tool.reversibility.value,
                "supervision": int(self.supervision),
                "rule": decision.rule,
                "allowed": decision.allowed,
                "needs_human": decision.needs_human,
                "target": intent.target,
            },
        )
        return tool, decision

    def _hold(self, intent: Intent, decision: Decision) -> Outcome:
        outcome = Outcome(intent=intent, decision=decision, ran=False)
        self.held.append(outcome)
        return outcome

    def _record_answer(
        self, intent: Intent, decision: Decision, tool: Tool, answer: tuple[bool, str]
    ) -> Outcome | None:
        """Log a person's answer. Returns the outcome when they refused."""
        approved, who = answer
        self.log.append(
            actor=f"user:{who}",
            kind="approval" if approved else "rejection",
            summary=f"{'Approved' if approved else 'Rejected'}: {intent.target or tool.name}",
            detail={"tool": tool.name, "rationale": intent.rationale},
        )
        if approved:
            return None
        return Outcome(intent=intent, decision=decision, ran=False, rejected_by=who)

    def _failed(
        self,
        intent: Intent,
        decision: Decision,
        tool: Tool,
        exc: Exception,
        elapsed: float,
        approved_by: str | None,
    ) -> Outcome:
        self.log.append(
            actor=f"agent:{self.agent_id}",
            kind="error",
            summary=f"{tool.name} failed: {exc}",
            detail={"tool": tool.name, "seconds": round(elapsed, 4)},
        )
        return Outcome(
            intent=intent,
            decision=decision,
            ran=False,
            error=str(exc),
            duration=Sourced(elapsed, DataOrigin.MEASURED, source="timer:tool_call"),
            approved_by=approved_by,
        )

    def _completed(
        self,
        intent: Intent,
        decision: Decision,
        tool: Tool,
        result: Any,
        elapsed: float,
        approved_by: str | None,
    ) -> Outcome:
        self.log.append(
            actor=f"agent:{self.agent_id}",
            kind="read" if tool.action in INERT_ACTIONS else "write",
            summary=f"{tool.name} completed on {intent.target or 'no named target'}",
            detail={
                "tool": tool.name,
                "seconds": round(elapsed, 4),
                "undo_available": tool.undo is not None,
                "approved_by": approved_by,
            },
        )
        return Outcome(
            intent=intent,
            decision=decision,
            ran=True,
            result=result,
            duration=Sourced(elapsed, DataOrigin.MEASURED, source="timer:tool_call"),
            approved_by=approved_by,
        )

    def _undo_target(self, outcome: Outcome) -> Tool | None:
        if not outcome.ran:
            return None
        tool = self.tools.get(outcome.intent.tool)
        if tool is None or tool.undo is None:
            self.log.append(
                actor=f"agent:{self.agent_id}",
                kind="undo",
                summary=f"No undo exists for {outcome.intent.tool}.",
                detail={"tool": outcome.intent.tool},
            )
            return None
        return tool

    def _undone(self, outcome: Outcome) -> None:
        self.log.append(
            actor=f"agent:{self.agent_id}",
            kind="undo",
            summary=f"Reversed {outcome.intent.tool} on {outcome.intent.target or 'no named target'}",
            detail={"tool": outcome.intent.tool},
        )


class Runner(_Supervisor):
    """Executes intents under supervision, recording every step."""

    def __init__(
        self,
        agent_id: str,
        supervision: SupervisionLevel | int,
        tools: list[Tool] | None = None,
        *,
        approver: Approver | None = None,
        log: AuditLog | None = None,
    ) -> None:
        super().__init__(agent_id, supervision, tools, log=log)
        self.approver: Approver = approver or AlwaysAsk()

    def submit(self, intent: Intent) -> Outcome:
        """Put one intent through the gate, and run it only if it clears."""
        tool, decision = self._gate(intent)
        if decision.blocked:
            return self._hold(intent, decision)

        approved_by: str | None = None
        if decision.needs_human:
            answer = self.approver(intent, decision)
            if answer is None:
                return self._hold(intent, decision)
            refused = self._record_answer(intent, decision, tool, answer)
            if refused is not None:
                return refused
            approved_by = answer[1]

        started = time.perf_counter()
        try:
            result = tool.run(intent.args)
        except Exception as exc:
            return self._failed(
                intent, decision, tool, exc, time.perf_counter() - started, approved_by
            )
        return self._completed(
            intent, decision, tool, result, time.perf_counter() - started, approved_by
        )

    def undo(self, outcome: Outcome) -> bool:
        """Reverse a completed action, if its tool can.

        Returns False rather than raising when there is nothing to undo,
        because "this cannot be taken back" is an answer the caller has
        to show a person, not an exception to swallow.
        """
        tool = self._undo_target(outcome)
        if tool is None or tool.undo is None:
            return False
        tool.undo(outcome.intent.args, outcome.result)
        self._undone(outcome)
        return True


async def _settle(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class AsyncRunner(_Supervisor):
    """:class:`Runner` for asynchronous hosts.

    The same gate, the same audit entries and the same outcomes; the only
    difference is that a tool's ``run`` and ``undo`` — and the approver —
    may be coroutines. A host whose tools touch a database or the network
    from an event loop uses this rather than blocking the loop.
    """

    def __init__(
        self,
        agent_id: str,
        supervision: SupervisionLevel | int,
        tools: list[Tool] | None = None,
        *,
        approver: Approver | AsyncApprover | None = None,
        log: AuditLog | None = None,
    ) -> None:
        super().__init__(agent_id, supervision, tools, log=log)
        self.approver: Approver | AsyncApprover = approver or AlwaysAsk()

    async def submit(self, intent: Intent) -> Outcome:
        """Put one intent through the gate, and run it only if it clears."""
        tool, decision = self._gate(intent)
        if decision.blocked:
            return self._hold(intent, decision)

        approved_by: str | None = None
        if decision.needs_human:
            answer = await _settle(self.approver(intent, decision))
            if answer is None:
                return self._hold(intent, decision)
            refused = self._record_answer(intent, decision, tool, answer)
            if refused is not None:
                return refused
            approved_by = answer[1]

        started = time.perf_counter()
        try:
            result = await _settle(tool.run(intent.args))
        except Exception as exc:
            return self._failed(
                intent, decision, tool, exc, time.perf_counter() - started, approved_by
            )
        return self._completed(
            intent, decision, tool, result, time.perf_counter() - started, approved_by
        )

    async def undo(self, outcome: Outcome) -> bool:
        """Reverse a completed action, if its tool can. See :meth:`Runner.undo`."""
        tool = self._undo_target(outcome)
        if tool is None or tool.undo is None:
            return False
        await _settle(tool.undo(outcome.intent.args, outcome.result))
        self._undone(outcome)
        return True
