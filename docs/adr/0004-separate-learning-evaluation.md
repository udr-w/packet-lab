# ADR-0004 — Learner evaluation is separated from tutoring in structure, and its limits are stated

**Status:** Accepted (with a Planned extension)

## Context

The agent that teaches also judges whether the learner understood. Left
implicit, that is a conflict of interest and easy to overclaim as an "assessed"
model.

## Decision

- Mastery is **structured and evidence-backed**: `learner.py` records per-concept
  evidence (prediction, observation, explanation, transfer, skip) that cites the
  lesson and run it came from, and a deterministic rule (`_derive_state`) decides
  the state — mastery requires an observation-or-transfer entry **and** an
  explanation entry; a skip never grants mastery.
- The limitation is stated plainly wherever mastery appears: it is
  **assistant-asserted**, not graded by an independent model. The evidence trail
  is the auditability mechanism — a reviewer can diff each summary against the
  committed lesson narrative in `docs/lessons/*.md`.

## Alternatives considered

- **Trust a single "mastered: true" flag from the agent.** Rejected: opaque and
  unfalsifiable.
- **A second model as grader now.** Deferred: valuable, but it would require a
  model-in-CI path this project deliberately keeps optional. Marked Planned.

## Consequences

- The deterministic gate (phases, evidence rule) is testable; the judgment part
  is honest about being probabilistic and human-auditable.
