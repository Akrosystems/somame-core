"""Permission mirroring, and the failures it must not paper over."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from somame_core.retrieval import (
    ACL_TTL,
    AclStale,
    Chunk,
    IdentityUnresolved,
    InMemoryIndex,
    Principal,
    RetrievalIndex,
    resolve_principals,
)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def chunk(cid, text, allow, vec=(1.0, 0.0), age=timedelta(minutes=1)):
    return Chunk(
        id=cid, source="sharepoint", document=f"doc-{cid}", text=text,
        vector=vec, allow=frozenset(allow), acl_read_at=NOW - age,
    )


FINANCE = Principal("group", "finance")
LEGAL = Principal("group", "legal")
ALICE = Principal("user", "alice")


@pytest.fixture
def index():
    return InMemoryIndex([
        chunk("c1", "Board pay review", [LEGAL]),
        chunk("c2", "Supplier terms", [FINANCE, LEGAL]),
        chunk("c3", "Petty cash policy", [FINANCE]),
    ])


def test_in_memory_index_satisfies_the_protocol():
    assert isinstance(InMemoryIndex(), RetrievalIndex)


def test_only_permitted_chunks_come_back(index):
    hits = index.search((1.0, 0.0), frozenset({FINANCE}), now=NOW)
    assert {h.chunk.id for h in hits} == {"c2", "c3"}


def test_a_chunk_the_asker_cannot_read_is_never_scored(index):
    """Not filtered afterwards — never considered."""
    hits = index.search((1.0, 0.0), frozenset({FINANCE}), now=NOW)
    assert all(h.chunk.id != "c1" for h in hits)


def test_empty_principals_fail_rather_than_returning_nothing(index):
    """The bug this whole module exists to prevent."""
    with pytest.raises(IdentityUnresolved):
        index.search((1.0, 0.0), frozenset(), now=NOW)


def test_an_unknown_asker_is_distinguishable_from_one_with_no_access(index):
    with pytest.raises(IdentityUnresolved):
        index.search((1.0, 0.0), frozenset(), now=NOW)
    # Someone real, with access to nothing, gets a clean empty list.
    assert index.search((1.0, 0.0), frozenset({Principal("user", "nobody")}), now=NOW) == []


def test_stale_permissions_raise_instead_of_being_served():
    stale = InMemoryIndex([chunk("c9", "old", [FINANCE], age=ACL_TTL + timedelta(minutes=1))])
    with pytest.raises(AclStale, match="Re-index it"):
        stale.search((1.0, 0.0), frozenset({FINANCE}), now=NOW)


def test_permissions_just_inside_the_ttl_are_served():
    fresh = InMemoryIndex([chunk("c9", "ok", [FINANCE], age=ACL_TTL - timedelta(seconds=1))])
    assert len(fresh.search((1.0, 0.0), frozenset({FINANCE}), now=NOW)) == 1


def test_results_are_ordered_by_distance():
    idx = InMemoryIndex([
        chunk("far", "x", [FINANCE], vec=(0.0, 1.0)),
        chunk("near", "x", [FINANCE], vec=(1.0, 0.0)),
    ])
    hits = idx.search((1.0, 0.0), frozenset({FINANCE}), now=NOW)
    assert [h.chunk.id for h in hits] == ["near", "far"]


def test_resolve_principals_refuses_an_anonymous_caller():
    with pytest.raises(IdentityUnresolved):
        resolve_principals(None, ["finance"])


def test_resolve_principals_builds_the_full_set():
    ps = resolve_principals("alice", ["finance"], ["approver"])
    assert ps == frozenset({ALICE, FINANCE, Principal("role", "approver")})


def test_limit_is_respected(index):
    assert len(index.search((1.0, 0.0), frozenset({FINANCE, LEGAL}), limit=1, now=NOW)) == 1
