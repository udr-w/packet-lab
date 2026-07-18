# ADR-0001 — Why Packet Lab uses an agent

**Status:** Accepted

## Context

Packet Lab teaches Linux networking by running real experiments on the
learner's machine and adapting to what the learner understands. Much of the
loop is mechanical (validate a command, enforce a budget, log a trace). Some of
it is not: choosing the next lesson, adapting an explanation to a specific
misconception, designing a novel experiment, and judging whether an answer
shows causal understanding.

## Decision

Use a single reasoning agent (the Claude Code assistant, governed by
`AGENTS.md`) for the judgment-bearing tasks only, and deterministic code for
everything with a correct implementation. The agent proposes; the control plane
disposes. Role names (Tutor, Experiment Designer, Tool Engineer, Reviewer) are
artifact contracts for the one agent, not separate processes or models.

## Alternatives considered

- **Pure scripted tutor.** Rejected: cannot adapt explanations, design new
  experiments, or judge free-text understanding.
- **Multi-agent system.** Rejected: nothing in a single-learner tutoring loop
  needs concurrent independent agents; it would add a message bus, coordination
  bugs, and cost for no teaching benefit, and it would be theatre to claim it.
- **Model-in-the-loop for safety decisions.** Rejected: safety must not depend
  on a prompt (see ADR-0002).

## Consequences

- The interesting engineering is the *control* around the agent, which is the
  portfolio point.
- The agent has repository write access, so its adherence to the control plane
  is procedural and audit-detectable, not physically enforced (see ADR-0002 and
  the threat model).
