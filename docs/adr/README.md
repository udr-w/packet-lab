# Architecture Decision Records

Concise records of the material decisions behind Packet Lab. Each states the
context, the decision, the alternatives considered, and the consequences. They
document decisions the codebase has actually made — not aspirational ones.

| ADR | Decision |
|---|---|
| [0001](0001-why-an-agent.md) | Why Packet Lab uses an agent (judgment only; deterministic code for everything else) |
| [0002](0002-deterministic-safety.md) | Safety is deterministic, generated tools are untrusted, and the runner is limits — not isolation |
| [0003](0003-reuse-before-generate.md) | Reuse an existing tool before generating a new one |
| [0004](0004-separate-learning-evaluation.md) | Learner evaluation is separated in structure, and its limits are stated |
| [0005](0005-structured-traces.md) | Run traces are structured, hash-chained JSONL; replay is honestly scoped |
| [0006](0006-json-file-state.md) | State is JSON files under an advisory lock, not a database |
| [0007](0007-sandbox-strategy.md) | Restricted runner now; namespace isolation is a documented gap |
| [0008](0008-single-agent-not-multi.md) | One reasoning agent with role contracts, not a multi-agent design |
