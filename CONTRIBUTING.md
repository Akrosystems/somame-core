# Contributing

Thank you for looking at Somame Core. It is MIT licensed, and external
contributions are welcome — with the caveat that this library is mostly
*restraint*, so the bar for change is deliberately high.

## Ground rules

1. **The mandatory escalation set never shrinks.** `DELETE`,
   `MOVE_MONEY`, `PUBLISH_EXTERNAL`, `CHANGE_ACCESS`, and any
   irreversible action, always need a human at every supervision level.
   A PR that weakens this will be closed, and CI is configured to fail
   if it lands by accident.
2. **No runtime dependencies.** The library that decides what needs a
   human must be auditable without reading a dependency tree. Development
   extras (`[dev]`) are fine.
3. **No fabricated data.** `DataOrigin` must never gain a member that
   lets invented values masquerade as measurements. `check_no_
   fabrication_member()` and CI both enforce this.
4. **Fail closed, say why.** Where the library cannot answer, it returns
   or raises with a reason — never a default that looks like an answer.

## Setting up

```bash
git clone https://github.com/Akrosystems/somame
cd somame
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest && mypy && ruff check src tests && ruff format --check src tests
```

## Before opening a pull request

- Every behaviour change ships with a test. The tests are written
  against public protocols (`RetrievalIndex`, `Approver`) so they do not
  over-fit implementations.
- `mypy` is strict and must pass.
- Public API changes update `CHANGELOG.md` under a new *Unreleased*
  heading, with the breaking ones flagged.
- The docstrings are part of the product here — if you change behaviour,
  change the words that describe it.

## Proposals

For anything that touches the gate, provenance or the audit format,
open an issue first with the problem, not the patch. These interfaces
are the ones we consider settled; they move only with a written rationale
and a major version.
