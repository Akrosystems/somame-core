# Architecture

Somame Core is six modules and no dependencies. This document maps how
they fit together, the one path every tool call takes, and where a host
application plugs in.

## Module map

```
                 your application (Somame Cloud, or your own)
                              │  declares Tools, supplies Approver
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │ runtime.py                                             │
   │   agent returns an Intent ──► Runner / AsyncRunner     │
   │         │ classifies against Tool.action/reversibility │
   │         ▼                                              │
   │   gate.py ─ decide(ActionClass, Reversibility,         │
   │                  SupervisionLevel)                     │
   │         │ allowed / needs approval / blocked / inert   │
   │         ▼                                              │
   │   tool invoked ──► Outcome ──► AuditEvent (audit.py)   │
   └────────────────────────────────────────────────────────┘
        │                    │                     │
        ▼                    ▼                     ▼
  provenance.py         retrieval.py          metrics.py
  what may be      permission-mirrored     honest reporting
  stored as a          search               over Sourced
  measurement                                figures
```

Dependency direction is one-way: `runtime` imports `gate` and `audit`;
everything else stands alone. `gate.py` imports nothing that could read
configuration — a CI gate proves it, because a gate that can be
configured is not a gate.

## The decision path

Every tool call, synchronous or asynchronous, takes the same five steps:

1. **Intent.** The agent never holds a tool. It returns an `Intent`
   naming a registered tool and its arguments.
2. **Classification.** The `Tool` itself declares its `ActionClass`
   (`READ`, `DRAFT`, `WRITE`, `DELETE`, `MOVE_MONEY`, `PUBLISH_EXTERNAL`,
   `CHANGE_ACCESS`, …) and `Reversibility`. Classification is data on the
   tool, not a judgement made at call time.
3. **Gate.** `decide()` applies two rules in order:
   - anything in `MANDATORY_ESCALATIONS`, or anything irreversible,
     needs a human at every supervision level;
   - otherwise the supervision level rules: levels 0–1 hold writes,
     levels 2–3 let reversible writes through. `INERT_ACTIONS` (read,
     draft) never wait at any level.
4. **Invocation or hold.** Allowed calls invoke the tool. Held calls ask
   the host's `Approver` (or `AsyncApprover`); a refusal is recorded as
   `Outcome(rejected)`, a granted one as `approved_by`. A `Runner` built
   without an approver holds rather than proceeds.
5. **Audit.** Every step of every path writes an `AuditEvent` to the
   hash-chained log. The synchronous and asynchronous runners share one
   implementation of this path, and a test asserts they write identical
   audit entries for identical intents.

## The audit chain

`AuditEvent` carries a `digest` that seals the event's content and the
previous event's digest. `AuditLog.verify()` walks the chain and reports
exactly where history was edited, removed or reordered. Hosts that keep
the chain in their own database call `AuditEvent.chained(seq, prev, ...)`
per row; the exported events still verify.

## Provenance and reporting

`Sourced[T]` pairs a value with its `DataOrigin` and refuses to exist
when the pairing is dishonest: `UNAVAILABLE` needs a reason, `RETRIEVED`
needs a source, and `MODEL_GEN` is never evidence. `metrics.summarise()`
computes its report exclusively over `Sourced` figures, which is why a
success rate over zero completed tasks is `None` with a reason rather
than `0%`. `summarise_totals()` runs the same rule code over pre-summed
per-day rollups, differing only in the median — unrecoverable from sums,
reported as unavailable with that reason rather than approximated.

## Permission-mirrored retrieval

`RetrievalIndex` is the protocol a real vector store implements. The
contract, enforced by the tests written against the protocol:

- `Chunk`s carry their ACL as `Principal`s at index time.
- `search(query, principals)` filters **inside** the search; a passage
  the asker cannot see cannot affect scores, ranks or summaries.
- Unresolvable identity raises `IdentityUnresolved` — fail closed, never
  "public only".
- Mirrored ACLs older than `ACL_TTL` raise `AclStale` rather than serve.

## Extension points

| You want to… | Implement |
| --- | --- |
| Run tools through the gate | Declare `Tool`s and drive `Runner`/`AsyncRunner` |
| Add a human approval step | Provide an `Approver` / `AsyncApprover` |
| Back retrieval with a real vector store | Implement `RetrievalIndex` |
| Keep the audit chain in your database | `AuditEvent.chained()` + `somame-core verify` |
| Add new action classes | Add the enum member and tests; `MANDATORY_ESCALATIONS` changes are review-gated by CI |

## Testing

The suite (~140 tests) needs no database and no network, on purpose: the
library that decides what needs a human must be testable everywhere it
might run. CI additionally asserts the escalation set has not shrunk and
that `gate.py` stays free of configuration imports.
