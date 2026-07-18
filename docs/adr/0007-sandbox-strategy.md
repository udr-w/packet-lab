# ADR-0007 — Restricted runner now; namespace isolation is a documented gap

**Status:** Accepted (with a Planned extension)

## Context

Ideal isolation for untrusted generated code would use Linux namespaces,
seccomp, and a network cut-off. Those depend on host support and privileges that
cannot be assumed on an arbitrary learner laptop.

## Decision

Build the strongest **portable** boundary now: a wall-clock deadline (primary),
`RLIMIT_CPU`/`RLIMIT_AS`/`RLIMIT_FSIZE`/`RLIMIT_NPROC` (backstops), a fully
replaced minimal environment with `HOME` pointed at the workspace, a refusal to
run as root, and process-group SIGKILL so nothing lingers. Pair it with the
AST validator as the primary gate. Call it a "restricted runner", never a
"sandbox".

`RLIMIT_NPROC` is applied only to untrusted generated tools, not to trusted
allow-listed binaries (dig/tcpdump spawn threads and a low per-user cap breaks
them); this trade-off is explicit in the code and the threat model.

## Alternatives considered

- **`unshare -rn` user+network namespaces.** Deferred to Planned: attractive
  because it would make `network: none` physically enforced, but it needs
  graceful degradation on hosts without unprivileged user namespaces, and the
  trace must record which mode actually ran.
- **Docker/gVisor.** Rejected as a base requirement: too heavy a dependency for
  a learner laptop and against the "run with one script" goal.

## Consequences

- `network: none` in a tool spec is currently enforced statically (no socket
  imports/opens pass the AST), not by the kernel. This is stated in the threat
  model as a residual (T1) with the namespace upgrade as the fix.
