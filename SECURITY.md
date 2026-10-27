# Security policy

## Reporting a vulnerability

Write to **security@akrosystems.com**. Do not open a public issue.

Include what you found, how to reproduce it, and the impact as you see
it. You will receive an acknowledgement within two working days and be
kept informed through triage, fix and coordinated disclosure. Researchers
acting in good faith will not be pursued.

## Scope

In scope: everything in `src/somame_core` — the gate and its mandatory
escalation set, provenance enforcement, the runners' approval path,
retrieval's fail-closed behaviour, the audit chain's tamper-evidence,
and the CLI.

Out of scope: Somame Cloud (see its own security policy), denial of
service by volume, and social engineering.

## What matters most here

This library's whole purpose is restraint, so the highest-value findings
are ones that let it quietly do less of that:

- A way to reach a tool without passing the gate
- A way to weaken, configure away or bypass `MANDATORY_ESCALATIONS`
- A path where fabricated data can be stored as a measurement
- A retrieval path that can serve passages the asker cannot access, or
  that fails open on unresolved identity
- A way to rewrite audit history without `verify()` noticing

## Our commitments

- Triage within two working days
- A patch and a coordinated disclosure for confirmed issues
- A release for any fix that affects the guarantees above, announced in
  the changelog with the security implication stated plainly
