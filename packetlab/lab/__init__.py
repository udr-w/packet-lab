"""Packet Lab control planes.

Deterministic infrastructure the tutoring agent must act through:

- specs       — structured tool and experiment specifications (typed, validated)
- policy      — command categories, capability checks, path validation
- governor    — Curriculum Governor: lesson state machine, scope, budgets
- curriculum  — curriculum graph loader/validator
- learner     — concept-level mastery model with evidence
- runner      — restricted subprocess execution (timeouts, output caps, rlimits)
- toolgen     — generated-tool lifecycle (validate, test, register, invoke, retire)
- trace       — structured JSONL run traces
- untrusted   — marking external text as data, never instructions

Nothing in this package calls a model. The reasoning agent (the Claude Code
assistant, per AGENTS.md) produces artifacts; this package decides whether
they may act, executes them under restriction, and records what happened.
"""
