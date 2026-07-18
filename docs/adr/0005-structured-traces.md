# ADR-0005 — Run traces are structured, hash-chained JSONL, and replay is honestly scoped

**Status:** Accepted

## Context

A reviewer must be able to answer "why was this lesson selected, why was this
command allowed, what did this tool do, what failed" without reading model
prose or opaque logs.

## Decision

Every important action emits a structured JSON event to
`state/runs/<run-id>/trace.jsonl` (one object per line). Each event carries the
sha256 of the previous event, forming a chain that `lab inspect --verify`
recomputes. Inspection (`lab inspect`, `--timeline`) is a first-class command.

Replay is deliberately scoped: `--timeline` re-renders recorded decisions; it
does **not** re-execute commands or re-run the model. That scope is stated so
"replay" is never mistaken for deterministic re-execution.

## Alternatives considered

- **Plain text logs.** Rejected: not machine-readable, not verifiable.
- **A database.** Rejected: JSONL is inspectable with standard tools, diffs
  cleanly, and needs no dependency.
- **Full deterministic replay.** Out of scope: would require recording and
  re-injecting every model decision and system response; the trace viewer plus
  the conformance evals cover the reviewer's needs.

## Consequences

- The chain makes out-of-band state edits detectable (see the threat model's
  two-tier boundary), which is what upgrades the trace from a diary to an audit
  record.
