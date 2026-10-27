"""Permission-mirrored retrieval: an agent reads only what its principal can.

The failure this module exists to prevent is specific. A naive design
indexes a company's documents, searches them by similarity, and then
filters the results by permission. That leaks: the ranking itself is
computed over documents the asker cannot see, and anything derived from
the ranking — a count, a "no results" versus "results you can't see", a
summary built before the filter — carries information out.

So the contract here is:

1. Access tags are copied onto each chunk **at index time**, from the
   source system's own ACL. Retrieval never calls out to ask.
2. The permission predicate is applied **inside** the search, before
   scoring is observed, not to its output.
3. If the asker's principals cannot be resolved, retrieval **fails**.
   It does not fall back to "public only", because a silent downgrade
   is indistinguishable from a correct empty result.

:class:`InMemoryIndex` is a reference implementation small enough to
read in full. A production index (pgvector, Elasticsearch, anything)
satisfies the same protocol; the test suite here is written against the
protocol so it can be pointed at either.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

__all__ = [
    "ACL_TTL",
    "AclStale",
    "Chunk",
    "IdentityUnresolved",
    "InMemoryIndex",
    "Principal",
    "PrincipalSet",
    "RetrievalIndex",
    "SearchHit",
    "resolve_principals",
]

#: How long a mirrored ACL may be trusted before it must be re-read from
#: the source. An hour is a deliberate compromise: short enough that a
#: revoked permission stops mattering the same working session, long
#: enough not to hammer the source system on every query.
ACL_TTL = timedelta(minutes=60)


class IdentityUnresolved(RuntimeError):
    """The asker's principals could not be established. Retrieval fails closed."""


class AclStale(RuntimeError):
    """A chunk's mirrored permissions are older than :data:`ACL_TTL`."""


@dataclass(frozen=True, slots=True)
class Principal:
    """One identity an asker holds: a user, a group, a role."""

    kind: str  # "user" | "group" | "role"
    id: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}"


PrincipalSet = frozenset[Principal]


@dataclass(frozen=True, slots=True)
class Chunk:
    """A passage, with the permissions it was carrying when indexed."""

    id: str
    source: str
    """The system of record it came from: 'sharepoint', 'gdrive', 'postgres:billing'."""
    document: str
    text: str
    vector: tuple[float, ...]
    allow: PrincipalSet
    """Principals permitted to read it, copied from the source ACL at index time."""
    acl_read_at: datetime
    """When that copy was taken. Checked against :data:`ACL_TTL` on every search."""
    meta: dict[str, str] = field(default_factory=dict)

    def readable_by(self, principals: PrincipalSet) -> bool:
        return bool(self.allow & principals)


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk: Chunk
    distance: float


@runtime_checkable
class RetrievalIndex(Protocol):
    """What any Somame-compatible index must do."""

    def index(self, chunks: Iterable[Chunk]) -> int: ...

    def search(
        self,
        query: Sequence[float],
        principals: PrincipalSet,
        *,
        limit: int = 8,
        now: datetime | None = None,
    ) -> list[SearchHit]: ...


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine distance. Present so the reference index is self-contained."""
    if len(a) != len(b):
        raise ValueError(f"Dimension mismatch: query has {len(a)}, chunk has {len(b)}.")
    dot = float(sum(x * y for x, y in zip(a, b, strict=True)))
    na = math.sqrt(float(sum(x * x for x in a)))
    nb = math.sqrt(float(sum(y * y for y in b)))
    if na == 0.0 or nb == 0.0:
        return 1.0
    return 1.0 - (dot / (na * nb))


class InMemoryIndex:
    """A small, readable reference index.

    It is not fast and is not meant to be. It exists so the access rule
    can be read in one sitting and tested without a database.
    """

    def __init__(self, chunks: Iterable[Chunk] | None = None) -> None:
        self._chunks: list[Chunk] = list(chunks or [])

    def __len__(self) -> int:
        return len(self._chunks)

    def index(self, chunks: Iterable[Chunk]) -> int:
        added = list(chunks)
        self._chunks.extend(added)
        return len(added)

    def search(
        self,
        query: Sequence[float],
        principals: PrincipalSet,
        *,
        limit: int = 8,
        now: datetime | None = None,
    ) -> list[SearchHit]:
        # Fail closed. An empty principal set is not "the public" — it is
        # "we do not know who is asking", and those must not look alike.
        if not principals:
            raise IdentityUnresolved(
                "No principals resolved for this request. Retrieval fails rather than "
                "falling back to a narrower scope, because a silent downgrade looks "
                "exactly like a correct empty result."
            )

        at = now or datetime.now(UTC)
        hits: list[SearchHit] = []
        for chunk in self._chunks:
            # The permission test happens here, before any score is kept,
            # so ranking never sees a passage the asker cannot read.
            if not chunk.readable_by(principals):
                continue
            if at - chunk.acl_read_at > ACL_TTL:
                raise AclStale(
                    f"Chunk {chunk.id} from {chunk.source} carries permissions read at "
                    f"{chunk.acl_read_at.isoformat()}, older than the {ACL_TTL} limit. "
                    "Re-index it before serving results from it."
                )
            hits.append(SearchHit(chunk=chunk, distance=_distance(query, chunk.vector)))

        hits.sort(key=lambda h: h.distance)
        return hits[:limit]


def resolve_principals(
    user_id: str | None,
    groups: Iterable[str] | None = None,
    roles: Iterable[str] | None = None,
) -> PrincipalSet:
    """Build a principal set, refusing to produce an empty one silently.

    A caller that cannot name the user has an authentication problem,
    not a retrieval problem, and should hear about it here rather than
    receive zero results later.
    """
    if not user_id:
        raise IdentityUnresolved(
            "No user id. The caller must establish who is asking before retrieval runs."
        )
    out: set[Principal] = {Principal("user", user_id)}
    out.update(Principal("group", g) for g in (groups or ()))
    out.update(Principal("role", r) for r in (roles or ()))
    return frozenset(out)
