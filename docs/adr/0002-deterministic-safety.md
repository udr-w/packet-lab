# ADR-0002 — Safety is deterministic, generated tools are untrusted, and the runner is limits not isolation

**Status:** Accepted

This ADR combines three decisions that form one coherent stance; separating
them would just restate the same reasoning three times.

## Context

The system executes model-proposed commands and model-generated code on a real
machine. If safety depended on the model "being careful", a single bad
generation or an injected instruction would be enough to cause harm.

## Decision

1. **Every safety-sensitive decision is code, not a prompt.** Command
   permission (`policy.py`), path containment, capability checks, resource
   limits (`runner.py`), schema validation (`specs.py`), and state transitions
   (`governor.py`) are deterministic and tested on both accept and reject paths.
2. **Generated tools are untrusted software.** Generated source is parsed and
   validated by an allow-by-exception AST check (`astcheck.py`) reading the
   exact bytes that will execute; it is unit-tested in isolation; its checksum
   is re-verified before every run. The generated test file is validated too.
3. **The runner is a restricted runner, explicitly not a sandbox.** It provides
   a wall-clock deadline, rlimits, a scrubbed environment, no-root, and
   process-group termination — but no namespace, seccomp, or network isolation.

## Alternatives considered

- **LLM-reviews-LLM safety.** Rejected: a second model reviewing the first's
  code is not a deterministic guarantee, and treating "another model approved
  it" as safety is exactly the trap this project avoids. A model may *assist*
  review, but registration is gated by deterministic validation + passing tests.
- **Deny-lists for command flags.** Rejected for the highest-risk binary
  (tcpdump): deny-lists miss bundled/renamed/future flags. tcpdump uses an
  allow-list; unknown flags are refused.
- **Full container/namespace isolation now.** Deferred (see ADR-0007): valuable
  but host-dependent; the strongest *portable* boundary is built now and the gap
  is documented honestly rather than overclaimed.

## Consequences

- The AST validator is load-bearing precisely because there is no OS-level FS or
  network sandbox; its limits are documented in the threat model with worked
  bypass examples and their rejections.
- Safety-sensitive behaviour is testable in isolation, which is why the eval
  suite can assert it.
