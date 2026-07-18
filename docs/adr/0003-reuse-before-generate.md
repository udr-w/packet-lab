# ADR-0003 — Reuse an existing tool before generating a new one

**Status:** Accepted

## Context

Generating code is the highest-risk and highest-cost action the agent can take.
Regenerating a tool that already exists wastes the validation/test pipeline and
multiplies the untrusted-code surface.

## Decision

`toolgen.lookup` runs a deterministic keyword/tag search over
`tools/registry.json` **first**. A tool is generated only when no adequate
registered tool exists. The Governor also caps generated tools per lesson
(`max_generated_tools`), so the reuse discipline is enforced by budget as well
as convention.

## Alternatives considered

- **Always generate fresh.** Rejected: needless untrusted-code surface and cost.
- **Semantic/embedding search for reuse.** Deferred: the registry is small and a
  keyword/tag match is deterministic, inspectable, and dependency-free.

## Consequences

- The registry is the tool memory; provenance explains why each tool exists.
- A drift test and an alignment eval assert the agent does not regenerate an
  existing tool.
