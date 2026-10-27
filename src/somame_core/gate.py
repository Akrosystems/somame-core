"""The Write Gate: which actions an agent may take without asking a human.

This is the part of Somame most worth reading with suspicion, which is
why it is the open part. The rule it encodes is short:

    Some actions always return to a human, at every supervision level,
    and no configuration can switch that off.

The mandatory set is a module constant, not a settings row and not a
database column, because a deployment that can edit it can defeat it.
Raising an agent's supervision level buys speed on routine work; it buys
nothing on a deletion, a payment, an external publication or an access
change.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "INERT_ACTIONS",
    "MANDATORY_ESCALATIONS",
    "ActionClass",
    "Decision",
    "GateError",
    "Reversibility",
    "SupervisionLevel",
    "decide",
    "requires_human",
]


class GateError(RuntimeError):
    """An action was attempted that the gate did not clear."""


class ActionClass(enum.Enum):
    """What an action does, independent of which tool does it."""

    READ = "read"
    DRAFT = "draft"
    """Produce output that changes nothing until a person uses it."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE_MONEY = "move_money"
    PUBLISH_EXTERNAL = "publish_external"
    """Anything that leaves the organisation: email, filings, posts, API calls to third parties."""
    CHANGE_ACCESS = "change_access"
    """Permissions, roles, keys, sharing, group membership."""
    EXECUTE = "execute"
    """Run code or a command whose effects are not known in advance."""


class Reversibility(enum.Enum):
    """Whether the action can be taken back, and at what cost."""

    REVERSIBLE = "reversible"
    """An undo payload exists and restores the prior state exactly."""
    COSTLY = "costly"
    """Recoverable, but through work: a restore, a correcting entry, a retraction."""
    IRREVERSIBLE = "irreversible"
    """Cannot be undone by this system. A sent email, a posted payment, a hard delete."""


class SupervisionLevel(enum.IntEnum):
    """How much latitude one agent has. Ordinal: comparisons are meaningful."""

    READ_ONLY = 0
    """Writes blocked entirely. Reads and drafts."""
    APPROVE_EVERY_WRITE = 1
    """Every write waits for a human. The default, and the only safe default."""
    NOTIFY_AND_UNDO = 2
    """The write lands, a human is told, and an undo payload is kept."""
    AUTONOMOUS_AUDITED = 3
    """No prompt for routine work. Still logged, still escalates the mandatory set."""


#: Actions that always return to a human. Not configurable, by construction.
MANDATORY_ESCALATIONS: Final[frozenset[ActionClass]] = frozenset(
    {
        ActionClass.DELETE,
        ActionClass.MOVE_MONEY,
        ActionClass.PUBLISH_EXTERNAL,
        ActionClass.CHANGE_ACCESS,
    }
)

#: Actions that change nothing and therefore never need a gate.
INERT_ACTIONS: Final[frozenset[ActionClass]] = frozenset({ActionClass.READ, ActionClass.DRAFT})


@dataclass(frozen=True, slots=True)
class Decision:
    """The gate's answer, with the reason it gave.

    The reason is not decoration. It is what the person sees when the
    approval reaches them, and what the audit log keeps.
    """

    allowed: bool
    """Whether the agent may proceed without a human right now."""
    needs_human: bool
    blocked: bool
    """True when no human can approve it either, because the agent may not write at all."""
    reason: str
    rule: str
    """Which rule decided: 'mandatory', 'irreversible', 'read_only', 'supervision', 'inert'."""
    undo_required: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def require(self) -> None:
        """Raise unless the action may proceed unattended."""
        if not self.allowed:
            raise GateError(self.reason)


def requires_human(
    action: ActionClass,
    reversibility: Reversibility,
    supervision_level: SupervisionLevel | int,
) -> bool:
    """Whether this action must be approved by a person before it runs.

    The three clauses, in the order they apply:

    1. Reads and drafts change nothing, so they never need a human.
    2. The mandatory set always does, at every level.
    3. An irreversible action always does, whatever its class.
    4. Otherwise it is a question of latitude: levels 0 and 1 ask.

    ``supervision_level`` accepts a plain ``int`` so a caller reading a
    level out of a database column does not have to coerce it first; the
    comparison is ordinal either way.
    """
    if action in INERT_ACTIONS:
        return False
    if action in MANDATORY_ESCALATIONS:
        return True
    if reversibility is Reversibility.IRREVERSIBLE:
        return True
    return int(supervision_level) <= int(SupervisionLevel.APPROVE_EVERY_WRITE)


def decide(
    action: ActionClass,
    reversibility: Reversibility,
    supervision_level: SupervisionLevel | int,
    *,
    target: str | None = None,
) -> Decision:
    """The full answer: may it proceed, must a human see it, and why.

    ``target`` is the thing being acted on, quoted back in the reason so
    the person approving reads "Delete 14 rows from settlements" rather
    than "Approve action?".
    """
    level = int(supervision_level)
    what = f"{action.value}" + (f" on {target}" if target else "")

    if action in INERT_ACTIONS:
        return Decision(
            allowed=True,
            needs_human=False,
            blocked=False,
            reason=f"{what} changes nothing, so it needs no approval.",
            rule="inert",
        )

    if level <= int(SupervisionLevel.READ_ONLY):
        return Decision(
            allowed=False,
            needs_human=False,
            blocked=True,
            reason=(
                f"This specialist is set to reads and drafts only, so {what} cannot run "
                "and cannot be approved into running. Raise its supervision level first."
            ),
            rule="read_only",
            tags=("blocked",),
        )

    if action in MANDATORY_ESCALATIONS:
        return Decision(
            allowed=False,
            needs_human=True,
            blocked=False,
            reason=(
                f"{what} is in the set that always returns to a person. "
                "Supervision level does not apply to it and no setting can switch it off."
            ),
            rule="mandatory",
            undo_required=reversibility is not Reversibility.IRREVERSIBLE,
            tags=("mandatory", action.value),
        )

    if reversibility is Reversibility.IRREVERSIBLE:
        return Decision(
            allowed=False,
            needs_human=True,
            blocked=False,
            reason=f"{what} cannot be undone, so a person decides it regardless of level.",
            rule="irreversible",
            tags=("irreversible",),
        )

    if level <= int(SupervisionLevel.APPROVE_EVERY_WRITE):
        return Decision(
            allowed=False,
            needs_human=True,
            blocked=False,
            reason=f"This specialist is on approve-every-write, so {what} waits for you.",
            rule="supervision",
            undo_required=True,
            tags=("supervision",),
        )

    return Decision(
        allowed=True,
        needs_human=False,
        blocked=False,
        reason=(
            f"{what} is reversible and this specialist is on "
            f"{SupervisionLevel(level).name.lower().replace('_', ' ')}. "
            "It proceeds, is logged, and keeps an undo payload."
        ),
        rule="supervision",
        undo_required=level == int(SupervisionLevel.NOTIFY_AND_UNDO),
        tags=("auto",),
    )
