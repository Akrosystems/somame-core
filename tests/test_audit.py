"""The chain detects edits and removals rather than merely discouraging them."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from somame_core.audit import GENESIS, AuditEvent, AuditLog, TamperDetected


def built():
    log = AuditLog()
    log.append("agent:a1", "decision", "held a delete", {"tool": "delete_row"})
    log.append("user:u1", "approval", "approved", {"who": "robert"})
    log.append("agent:a1", "write", "deleted 14 rows", {"rows": 14})
    return log


def test_a_fresh_log_starts_at_genesis():
    assert AuditLog().head == GENESIS


def test_a_clean_chain_verifies():
    built().verify()


def test_editing_an_entry_is_caught():
    log = built()
    tampered = AuditEvent(**{**asdict(log[1]), "summary": "approved something else"})
    log._events[1] = tampered
    with pytest.raises(TamperDetected, match="contents were changed"):
        log.verify()


def test_removing_an_entry_is_caught():
    log = built()
    del log._events[1]
    with pytest.raises(TamperDetected):
        log.verify()


def test_reordering_is_caught():
    log = built()
    log._events[1], log._events[2] = log._events[2], log._events[1]
    with pytest.raises(TamperDetected):
        log.verify()


def test_appending_does_not_break_the_chain():
    log = built()
    log.append("agent:a1", "undo", "reversed it")
    log.verify()
    assert len(log) == 4


def test_a_round_trip_through_jsonl_verifies():
    log = built()
    again = AuditLog.from_jsonl(log.to_jsonl())
    again.verify()
    assert again.head == log.head


def test_each_entry_links_to_the_one_before():
    log = built()
    assert log[1].prev == log[0].digest
    assert log[2].prev == log[1].digest
