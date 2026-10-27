"""Somame Core — the supervised agent runtime.

MIT licensed. This is the part of Somame worth reading with suspicion:
the gate that decides which actions return to a human, the provenance
types that make fabricated data unstorable, the retrieval contract that
binds permissions to passages at index time, and the reporting that
leaves a blank rather than inventing a number.

Somame Cloud, the hosted platform, is separate and proprietary. It
depends on this package; nothing here depends on it.
"""

from .audit import GENESIS, AuditEvent, AuditLog, TamperDetected
from .gate import (
    INERT_ACTIONS,
    MANDATORY_ESCALATIONS,
    ActionClass,
    Decision,
    GateError,
    Reversibility,
    SupervisionLevel,
    decide,
    requires_human,
)
from .metrics import Report, TaskRecord, Totals, summarise, summarise_totals
from .provenance import (
    DataOrigin,
    ProvenanceError,
    Sourced,
    Unavailable,
    check_no_fabrication_member,
)
from .retrieval import (
    ACL_TTL,
    AclStale,
    Chunk,
    IdentityUnresolved,
    InMemoryIndex,
    Principal,
    RetrievalIndex,
    SearchHit,
    resolve_principals,
)
from .runtime import (
    AlwaysAsk,
    Approver,
    AsyncApprover,
    AsyncRunner,
    DenyAll,
    Intent,
    Outcome,
    Runner,
    Tool,
    ToolNotRegistered,
)

__version__ = "0.2.0"

__all__ = [
    "ACL_TTL",
    "GENESIS",
    "INERT_ACTIONS",
    "MANDATORY_ESCALATIONS",
    "AclStale",
    "ActionClass",
    "AlwaysAsk",
    "Approver",
    "AsyncApprover",
    "AsyncRunner",
    "AuditEvent",
    "AuditLog",
    "Chunk",
    "DataOrigin",
    "Decision",
    "DenyAll",
    "GateError",
    "IdentityUnresolved",
    "InMemoryIndex",
    "Intent",
    "Outcome",
    "Principal",
    "ProvenanceError",
    "Report",
    "RetrievalIndex",
    "Reversibility",
    "Runner",
    "SearchHit",
    "Sourced",
    "SupervisionLevel",
    "TamperDetected",
    "TaskRecord",
    "Tool",
    "ToolNotRegistered",
    "Totals",
    "Unavailable",
    "__version__",
    "check_no_fabrication_member",
    "decide",
    "requires_human",
    "resolve_principals",
    "summarise",
    "summarise_totals",
]
