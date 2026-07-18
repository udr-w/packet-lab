# ADR-0006 — State is JSON files under an advisory lock, not a database

**Status:** Accepted

## Context

Lesson state, the learner model, and the tool registry are read-modify-written
by short-lived CLI processes that can overlap (Claude Code batches Bash calls).

## Decision

Store state as plain JSON files (`state/lesson.json`, `state/learner.json`,
`tools/registry.json`) written via `statefile.py`: an advisory `flock` around
each load-mutate-save, atomic temp-plus-rename writes, and a `generation`
counter that makes a stale write fail loudly (`StaleStateError`).

## Alternatives considered

- **SQLite.** Rejected: adds a dependency and opacity for data a reviewer
  benefits from reading directly; the concurrency need is met by an advisory
  lock.
- **Plain writes with no lock.** Rejected: atomic rename prevents torn files but
  not lost updates; two overlapping CLI calls would clobber each other.

## Consequences

- State is diff-friendly and human-readable.
- The lock is advisory and same-host, which matches the single-operator design.
