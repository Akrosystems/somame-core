"""An append-only record of what was decided and what was done.

Hash-chained, so a deleted or edited entry is detectable rather than
merely discouraged. This is not a blockchain and makes no distributed
claim: it means that if someone rewrites history in the store,
:meth:`AuditLog.verify` says where.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = ["AuditEvent", "AuditLog", "TamperDetected"]

GENESIS = "0" * 64


class TamperDetected(RuntimeError):
    """The chain does not reproduce: an entry was changed or removed."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One thing that happened, and the hash that binds it to the last one."""

    seq: int
    at: str
    actor: str
    """Who or what acted: 'agent:e17', 'user:u1', 'system'."""
    kind: str
    """'decision', 'write', 'approval', 'rejection', 'undo', 'error'."""
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)
    prev: str = GENESIS
    digest: str = ""

    def body(self) -> str:
        """The canonical bytes the digest covers."""
        return json.dumps(
            {
                "seq": self.seq,
                "at": self.at,
                "actor": self.actor,
                "kind": self.kind,
                "summary": self.summary,
                "detail": self.detail,
                "prev": self.prev,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def compute_digest(self) -> str:
        return hashlib.sha256(self.body().encode("utf-8")).hexdigest()


class AuditLog:
    """An in-memory append-only log.

    A host system will keep these rows in its own store; this class is
    the reference for how they chain, and is usable on its own for
    tests, for a local run, and for verifying an exported chain.
    """

    def __init__(self, events: Iterable[AuditEvent] | None = None) -> None:
        self._events: list[AuditEvent] = list(events or [])

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[AuditEvent]:
        return iter(self._events)

    def __getitem__(self, i: int) -> AuditEvent:
        return self._events[i]

    @property
    def head(self) -> str:
        return self._events[-1].digest if self._events else GENESIS

    def append(
        self,
        actor: str,
        kind: str,
        summary: str,
        detail: dict[str, Any] | None = None,
        *,
        at: str | None = None,
    ) -> AuditEvent:
        draft = AuditEvent(
            seq=len(self._events),
            at=at or _now(),
            actor=actor,
            kind=kind,
            summary=summary,
            detail=dict(detail or {}),
            prev=self.head,
        )
        event = AuditEvent(**{**asdict(draft), "digest": draft.compute_digest()})
        self._events.append(event)
        return event

    def verify(self) -> None:
        """Walk the chain. Raise :class:`TamperDetected` at the first break."""
        prev = GENESIS
        for i, e in enumerate(self._events):
            if e.seq != i:
                raise TamperDetected(f"Entry at position {i} claims sequence {e.seq}.")
            if e.prev != prev:
                raise TamperDetected(
                    f"Entry {e.seq} follows {e.prev[:12]}… but the previous entry hashes to {prev[:12]}… "
                    "An entry was removed or reordered."
                )
            recomputed = e.compute_digest()
            if recomputed != e.digest:
                raise TamperDetected(
                    f"Entry {e.seq} does not hash to its recorded digest. Its contents were changed."
                )
            prev = e.digest

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(asdict(e), sort_keys=True, default=str) for e in self._events)

    @classmethod
    def from_jsonl(cls, text: str) -> AuditLog:
        events = [AuditEvent(**json.loads(line)) for line in text.splitlines() if line.strip()]
        return cls(events)
