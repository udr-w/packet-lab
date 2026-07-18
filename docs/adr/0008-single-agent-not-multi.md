# ADR-0008 — One reasoning agent with role contracts, not a multi-agent architecture

**Status:** Accepted

## Context

The problem looks like it wants a multi-agent framing (a Tutor, a Designer, an
Engineer, a Reviewer) — but it does not. It would be easy and dishonest to
present these as separate agents.

## Decision

There is exactly one reasoning agent. Tutor / Experiment Designer / Tool
Engineer / Reviewer / Learning Evaluator are **artifact contracts** for that one
agent: each names a structured output (a decision, an ExperimentSpec, a ToolSpec
+ source, an evidence record) and the boundaries the control plane enforces on
it. Independent safety review is provided **deterministically** (policy + AST +
tests), not by a second model. Terminology is enforced: `lab doctor` fails if
`docs/` ever describes the system as "multi-agent" or a "swarm" — the rule is
that it never does so without an explicit negation.

## Alternatives considered

- **True multi-agent (separate processes/models).** Rejected: no teaching
  benefit for a single-learner loop, real coordination cost, and it would
  misrepresent the system.
- **A second model as the independent reviewer.** Rejected as the *safety*
  mechanism (deterministic validation is the gate); a separate-model learning
  evaluator remains a Planned enhancement, clearly labelled.

## Consequences

- The architecture diagram shows one agent with contracts flowing into the
  deterministic planes, never three actor boxes.
- Claims stay defensible under scrutiny: the impressive part is the control, not
  a headcount of agents.
