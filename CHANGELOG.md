# Changelog

All notable changes to Somame Core. The mandatory escalation set has not
changed in any release and will not shrink in any release.

## 0.2.0

### Added

- `AsyncRunner` and `AsyncApprover`: the supervised runner for hosts on an
  event loop. Tools, undo functions and approvers may be coroutines. Both
  runners now share one implementation of the decision path, so the
  synchronous and asynchronous paths cannot drift; a test asserts they
  write identical audit entries for identical intents.
- `Totals` and `summarise_totals()`: reporting from pre-summed work (for
  example per-day rollups) under exactly the same rules as `summarise()`.
  The median is reported as unavailable, with its reason, because it
  cannot be recovered from sums.
- `AuditEvent.chained()`: seal one event against a stored head, for hosts
  that keep the chain in their own database. `GENESIS` is now exported.
- `INERT_ACTIONS` is now public (it was the private `_INERT`).
- `py.typed`, so type checkers use the package's annotations.

### Fixed

- `Outcome.held` was `True` for an action a person had **rejected**, so a
  refusal was indistinguishable from an action still waiting for an
  answer. Rejections now carry `rejected_by`, report `rejected`, and are
  not held.
- A `READ` or `DRAFT` tool declared `REVERSIBLE` no longer has to supply a
  dummy `undo`: an action that changes nothing has nothing to put back.
- `retrieval.__all__` now lists `resolve_principals`.

### Changed

- `Outcome.approved_by` is no longer set on a rejection; use
  `Outcome.rejected_by`.

## 0.1.0

First release: the write gate, provenance types, permission-mirrored
retrieval, honest reporting, the supervised runner and the audit chain.
