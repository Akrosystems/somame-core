# Somame Core

**MIT licensed.** The supervised agent runtime behind [Somame](https://somame.ai).

Somame employs credentialed AI specialists into a company's workforce.
The hosted platform — tenancy, billing, the workforce office, the role
catalog — is **Somame Cloud**, and it is proprietary. *This* repository
is the part that decides what an agent is allowed to do and what it is
allowed to claim, and it is open because those are the two things you
should not have to take a vendor's word for.

Somame Cloud depends on this package. Nothing here depends on Cloud.

```bash
pip install somame-core
somame-core gate     # the full decision table, every action at every level
somame-core demo     # an agent on the most permissive setting tries to delete something
```

The name is from the Ghanaian *"soma me"* — "send me".

---

## What is in here

Four ideas, each small enough to read in full.

### 1. The Write Gate — `somame_core.gate`

Four classes of action always return to a human, at **every** supervision
level including the most autonomous one: `DELETE`, `MOVE_MONEY`,
`PUBLISH_EXTERNAL`, `CHANGE_ACCESS`. So does anything irreversible,
whatever its class.

```python
from somame_core import ActionClass, Reversibility, SupervisionLevel, decide

d = decide(ActionClass.DELETE, Reversibility.REVERSIBLE,
           SupervisionLevel.AUTONOMOUS_AUDITED, target="settlements")
d.needs_human   # True — level 3 does not exempt a deletion
d.rule          # "mandatory"
```

The set is a module-level `frozenset`, not a settings row and not a
database column, because a deployment that can edit it can defeat it.
A CI gate asserts it has not shrunk, and a second one asserts that
`gate.py` imports nothing that could read configuration.

Raising an agent's level buys speed on routine, reversible work. It buys
nothing on the four.

### 2. Provenance — `somame_core.provenance`

`DataOrigin` has five members: `MEASURED`, `RETRIEVED`, `USER_STATED`,
`MODEL_GEN`, `UNAVAILABLE`. There is deliberately **no** `SAMPLE`,
`DEMO`, `MOCK`, `PLACEHOLDER` or `ESTIMATED`. Invented data has no way
to be labelled, so it has no way to be stored and later shown as a
measurement.

`Sourced[T]` enforces two things at construction, not at display:

```python
Sourced(42.0, DataOrigin.UNAVAILABLE, reason="…")  # ProvenanceError
Sourced(1.0, DataOrigin.RETRIEVED)                 # ProvenanceError: no source named
Unavailable("No baseline is on record.")           # fine, and it says why
```

`MODEL_GEN` is storable and showable, but `is_evidence` is `False`: a
model's guess is a legitimate thing to keep, and an illegitimate thing
to put behind a reported figure.

### 3. Permission-mirrored retrieval — `somame_core.retrieval`

The failure this prevents is specific. Index a company's documents,
rank them by similarity, *then* filter by permission, and the ranking
itself has already been computed over documents the asker cannot see.
So:

* Access tags are copied onto each passage **at index time**, from the
  source system's own ACL.
* The permission test runs **inside** the search, before any score is
  kept — never over its output.
* An unresolved identity **raises**. It does not quietly fall back to
  "public only", because a silent downgrade is indistinguishable from a
  correct empty result.

```python
index.search(query, frozenset())   # IdentityUnresolved, not []
```

Mirrored ACLs older than `ACL_TTL` (one hour) raise rather than serve.
`InMemoryIndex` is a reference implementation; the tests are written
against the `RetrievalIndex` protocol so they can be pointed at a real
one.

### 4. Honest reporting — `somame_core.metrics`

```python
summarise([]).success_rate.value          # None, not 0.0
```

Three rules:

* **No completed work means no success rate.** An agent that has done
  nothing has not failed at anything.
* **Hours returned need a baseline for every task counted**, and the
  baseline must be evidence. One task without one blanks the total
  rather than understating it while looking like the total.
* **Money needs a rate the customer stated.** Value, net return and
  return on cost are arithmetic on an internal hourly cost only the
  customer knows. A rate with any origin other than `USER_STATED` is
  refused — including one this library could have inferred. There is no
  default and no estimator.

Every blank carries its reason, so a dash on a report is never
ambiguous with a bug.

A host that keeps per-day rollups rather than every task record uses
`summarise_totals(Totals(...))`. It runs the same rule code as
`summarise()` and differs in exactly one figure: the median, which
cannot be recovered from sums and is reported as unavailable, with that
reason, rather than approximated.

```python
week = Totals.sum(daily_totals)          # Totals add
summarise_totals(week, cost=cost, hourly_rate=rate)
```

### Plus: the runner and the audit chain

`somame_core.runtime` arranges things so a tool **cannot** be reached
except through the gate. The agent never holds a tool; it returns an
`Intent`, and the `Runner` classifies, gates, and only then invokes.
A `Tool` declares its `ActionClass` and `Reversibility` as part of its
identity.

A `Runner` built without an approver **holds** rather than proceeds. A
person's refusal is recorded as such (`outcome.rejected`), never as a
hold still waiting for an answer.

`AsyncRunner` is the same runner for hosts on an event loop: tools,
undo functions and the approver may be coroutines. Both runners share
one implementation of the decision path, and a test asserts they write
identical audit entries for identical intents.

`somame_core.audit` is an append-only, hash-chained log. `verify()`
says where an entry was edited, removed or reordered. A host that keeps
the chain in its own database seals each row with
`AuditEvent.chained(seq=..., prev=head_digest, ...)` and its export
still verifies with `somame-core verify`.

---

## Why this is the open half

Somame's pitch is that you can hand work to an AI specialist without
handing it the ability to quietly do something you would not have
allowed, and without it reporting progress it cannot substantiate. Both
of those are claims about restraint, and a claim about restraint from a
closed-source vendor is worth very little.

So the restraint is here, readable, installable and testable on its own,
under a licence that lets you fork it if we ever weaken it.

What is **not** here, and is proprietary: the multi-tenant platform, the
billing, the orbital workforce office, the 356-role credentialed
catalog, the connector implementations, and the hosted operations.

---

## Development

```bash
git clone https://github.com/akrosystems/somame
cd somame
pip install -e ".[dev]"
pytest          # 136 tests, no database, no network
mypy            # strict
ruff check src tests && ruff format --check src tests
```

No runtime dependencies, on purpose. The part of a system that decides
what needs a human should be auditable without reading a dependency
tree.

## Status

`0.2.0` — see [CHANGELOG.md](CHANGELOG.md). The interfaces in `gate`
and `provenance` are the ones we consider settled; `runtime` and
`retrieval` may still move. Breaking changes will go through a major
version, and the mandatory escalation set will not shrink in any version.

## Licence

MIT — see [LICENSE](LICENSE). Somame Cloud is separate and proprietary.
