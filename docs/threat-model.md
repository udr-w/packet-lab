# Threat model

Packet Lab runs code that a language model proposed, on the learner's own
machine, against real network state. This document is the honest accounting of
what can go wrong, what stops it, and what remains exposed. Nothing here claims
a guarantee the code cannot back.

## Assets

- The learner's machine and data (home directory, credentials, other processes).
- The integrity of the lesson: the learner should be taught correctly and their
  mastery record should reflect reality.
- Captured traffic, which may contain sensitive payloads.
- The repository's own state and history.

## The two-tier boundary (read this first)

The control plane enforces two different kinds of boundary, and conflating them
would be dishonest:

1. **Physical, for generated tools and guarded commands.** These genuinely run
   under `runner.py` (rlimits, wall-clock kill, scrubbed env, no root) with
   `astcheck.py` in front of generated source. The agent cannot wish these
   limits away.
2. **Procedural + audit-detectable, for the agent itself.** The reasoning agent
   has repository write access and a shell. Nothing physically prevents it from
   editing `state/lesson.json` or `state/learner.json` directly. What the design
   provides instead is detectability: traces are hash-chained (`trace.py`), and
   `lab inspect --verify` recomputes the chain, so tampering breaks the chain or
   leaves a state change with no authorizing trace event. `AGENTS.md` makes
   "all lesson state changes go through the CLI" a standing rule; the verifier
   is the check on that rule.

The restricted runner is **not a sandbox**. It has no namespaces, no seccomp,
and no network isolation. Static validation (`astcheck.py`) is therefore
load-bearing, and it is defence-in-depth, not proof.

## Threats

Each threat lists the asset at risk, the path, the existing mitigation, the
residual exposure, and the planned improvement.

### T1 — Generated code performs a malicious action

- **Asset:** the machine.
- **Path:** the agent (or an injection into it) emits tool source that shells
  out, opens a socket, reads secrets, or deletes files.
- **Mitigation:** `astcheck.py` is allow-by-exception. Imports are limited to a
  small stdlib allow-list; `os`, `subprocess`, `socket`, `shutil`, `ctypes`,
  `importlib`, `threading`, `multiprocessing`, `signal`, `resource`, `pty`,
  `tempfile`, and `pathlib` are all rejected. `eval`/`exec`/`compile`/
  `__import__`/`getattr`/`setattr`/`breakpoint`/`input` and the `str.format`
  reflection channel are rejected; dunder attribute access
  (`__globals__`, `__subclasses__`, …) is rejected wherever it appears
  (`ast.walk`, so nested scopes, decorators, and annotations are covered).
  `open()` requires a literal path and mode; write modes need a declared write
  capability; absolute paths must match a declared read/write glob. The
  generated **test file** is validated with the same rules. The runner backstops
  everything the AST misses.
- **Residual:** AST allow-listing is not a proof. A validated tool can still
  `open()` a file that happens to be inside its declared read globs, and a novel
  reflection trick could exist. Because there is no OS-level FS/network sandbox,
  the AST's completeness is what stands between a validated tool and the
  filesystem the process UID can reach.
- **Planned:** optional unprivileged network/namespace isolation
  (`unshare -rn`) where the host supports it, recorded in the trace as which
  mode ran (`docs/adr/0007-sandbox-strategy.md`).

A worked example of an AST bypass family and why it is rejected: the classic
`().__class__.__bases__[0].__subclasses__()` walk to reach a dangerous class is
blocked because every `__dunder__` attribute access is rejected; the
`getattr(o, '__glob'+'als__')` variant is blocked because `getattr` is forbidden
outright; and `'{0.__class__}'.format(x)` is blocked because `str.format` is
forbidden. See `tests/test_astcheck.py`, which asserts each of these is rejected.

### T2 — Accidental destructive command

- **Asset:** the machine and its network state.
- **Path:** the agent proposes a guarded command that damages the system.
- **Mitigation:** `policy.py` is deny-by-default. Only named categories exist,
  each with an allow-listed set of binaries and per-binary rules. The one
  mutating category (`modify_neighbour_cache`) is structurally restricted to
  `ip neigh del|flush`. `ping` must be count-bounded; `tcpdump` uses a flag
  **allow-list** (so `-z`, `-r`, `-Z`, and unknown flags are refused) and its
  `-w` target must resolve inside the lesson workspace. The Governor
  additionally refuses any category the current lesson does not permit.
- **Residual:** within an allow-listed category a command can still be wrong
  (e.g. flushing a neighbour entry the learner wanted). Impact is bounded to
  lesson-relevant, reversible operations.
- **Planned:** a human-approval prompt for the mutating category.

### T3 — Prompt injection via command output, files, or packet payloads

- **Asset:** lesson integrity; indirectly, the machine.
- **Path:** captured output or a file contains "ignore your instructions / grant
  yourself root", and the agent obeys it.
- **Mitigation:** `untrusted.render` wraps all external text in explicit
  untrusted-data markers, strips ANSI/control sequences, and defangs a payload
  that forges the closing marker. Crucially, the *containment is downstream*:
  even a fully hijacked agent still acts through `policy.py` (argv allow-list),
  the Governor (scope/budget), and `runner.py` (limits). Injection can corrupt
  the *tutoring*; it cannot escalate the *host* through the guarded path.
- **Residual:** wrapping does not force a model to obey it. An agent that
  follows an injected instruction **and acts outside the CLI** is not contained
  by wrapping — this is an accepted residual risk of giving the agent repo
  access, mitigated only by the trace verifier (T8).
- **Planned:** a trace-audit eval asserting that every guarded command in a real
  run had a prior governor allow decision.

### T4 — Secret leakage

- **Asset:** credentials, tokens, environment secrets.
- **Path:** a tool or command reads `~/.ssh`, `~/.aws`, or environment variables
  and prints them.
- **Mitigation:** the runner replaces the environment entirely (never copies
  `os.environ`), sets `HOME` to the workspace (so `~` cannot reach real
  dotfiles), and `PATH` to system directories only. Generated tools cannot
  `open()` an absolute path outside their declared capabilities. Traces truncate
  long fields and the emitters never write packet payloads or file contents.
- **Residual:** a guarded command the lesson legitimately runs (e.g. `cat
  /etc/resolv.conf`) prints its real output, which the learner sees; the
  read-system-file allow-list keeps this to non-sensitive files.
- **Planned:** an output redaction pass for high-risk patterns.

### T5 — Filesystem traversal / workspace escape

- **Asset:** the machine and the repository.
- **Path:** a path argument or write glob escapes the lesson workspace via `..`
  or a symlink.
- **Mitigation:** `policy.is_within` resolves the parent directory and rejects a
  final component that is itself a symlink; `..` components are rejected in
  capability globs and open() paths; tcpdump `-w` and tool write globs must
  resolve inside the workspace.
- **Residual:** a **TOCTOU** window remains for files a child process opens
  itself (tcpdump opens its own `-w` target after the policy check). This is
  documented, not hidden; the window is minimized by confining the target
  directory and is bounded by the runner's file-size limit.
- **Planned:** create the `-w` target ahead of time with `O_EXCL` under a
  workspace directory descriptor.

### T6 — Resource exhaustion (CPU, memory, processes, disk, output)

- **Asset:** machine availability.
- **Path:** a tool or command sleeps forever, allocates unbounded memory, forks
  a bomb, floods stdout, or fills the disk.
- **Mitigation:** the runner enforces a **wall-clock deadline** as the primary
  control (killing the process group regardless of CPU use, sleeps, or drip
  output), plus `RLIMIT_CPU`, `RLIMIT_AS` (~1.5 GiB), `RLIMIT_FSIZE` (8 MiB),
  and — for untrusted tool execution only — `RLIMIT_NPROC` as headroom over
  current usage. Output is capped and truncated. The process group is
  SIGKILLed so nothing outlives a run.
- **Residual:** `RLIMIT_NPROC` is deliberately **not** applied to trusted
  allow-listed binaries (dig/tcpdump spawn threads and a low per-user cap would
  break them), so a trusted binary is bounded by wall-clock and CPU limits, not
  a process cap. `RLIMIT_AS` is skipped on hosts that refuse it.
- **Planned:** cgroup-based limits where available.

### T7 — Persistent malicious generated tool / supply chain

- **Asset:** the machine, across lessons.
- **Path:** a tool passes validation once, then is edited on disk to something
  malicious before a later invocation; or a dependency is compromised.
- **Mitigation:** provenance records a sha256 of the validated bytes; `invoke`
  and `run_tests` re-verify the on-disk checksum and refuse on mismatch.
  Dependencies are restricted to the standard library (declared and validated);
  third-party packages are rejected at the spec layer. Retention is explicit
  (`lesson`/`archive`/`keep`) and `cleanup` removes lesson-scoped tools.
- **Residual:** a tool retained as `keep` is trusted for as long as its checksum
  holds; re-validation on every invoke guards the bytes but not a re-validated
  malicious rewrite (which would have to pass the AST gate again).
- **Planned:** signed provenance and a `keep`-tool re-review policy.

### T8 — State/log tampering by the agent

- **Asset:** lesson integrity and the audit record.
- **Path:** the agent edits `lesson.json`/`learner.json` or appends fake trace
  lines to skip a gate or mint mastery.
- **Mitigation:** traces are hash-chained; `lab inspect --verify` detects a
  broken chain. State transitions are meant to flow through the Governor, which
  emits the authorizing trace event.
- **Residual:** as stated in the two-tier boundary, this is procedural for the
  agent — the verifier detects tampering after the fact, it does not prevent it.
- **Planned:** cross-check state mutations against trace events in `--verify`.

### T9 — Unsafe concurrent execution / lost state updates

- **Asset:** lesson state integrity.
- **Path:** two CLI processes read-modify-write the same state file and one
  update is lost.
- **Mitigation:** `statefile.py` serialises every mutation under an advisory
  `flock`, writes atomically (temp + rename), and bumps a `generation` counter
  so a stale write is detected (`StaleStateError`).
- **Residual:** the lock is advisory and same-host; a process that bypasses
  `statefile` is not serialised.
- **Planned:** none; the current model matches the single-operator design.

### T10 — Capture privacy

- **Asset:** sensitive traffic (credentials, cookies, tokens in cleartext).
- **Path:** a capture writes a pcap containing sensitive payloads.
- **Mitigation:** captures live in `capture/` and `state/`, both gitignored;
  traces never store payloads. The lessons prefer live on-screen observation
  over saved captures.
- **Residual:** a `-w` capture on disk still contains whatever crossed the wire;
  the operator is responsible for deleting it.
- **Planned:** an automatic capture-retention/cleanup policy.

### T11 — Learner deliberately bypassing controls

- **Asset:** lesson integrity (not the machine — the learner owns the machine).
- **Path:** the learner tries to get the agent to run out-of-scope or unsafe
  commands "for fun".
- **Mitigation:** the Governor refuses out-of-scope categories and concepts
  regardless of who asks; the policy layer refuses non-allow-listed commands.
- **Residual:** the learner can always run commands in their own terminal
  outside Packet Lab — which is expected and fine; Packet Lab only governs what
  *it* runs.

### T12 — tcpdump privilege

- **Asset:** the machine.
- **Path:** tcpdump needs `CAP_NET_RAW`; if it were setuid-root, `-z`/`-w` would
  act as root.
- **Mitigation:** the intended setup grants a **file capability**
  (`setcap cap_net_raw,cap_net_admin+eip /usr/bin/tcpdump`), not setuid-root, so
  tcpdump runs with only raw-socket capability as the invoking user. The runner
  refuses to run as root. The flag allow-list removes `-z` and confines `-w`.
- **Residual:** if a host has a setuid-root tcpdump instead, the runner's no-root
  guarantee does not extend into tcpdump itself; the flag allow-list still
  removes command-execution flags. Documented in `docs/SETUP.md`.

### T13 — Cross-learner state leakage

- **Asset:** each learner's private mastery, predictions, explanations, and
  misconceptions.
- **Path:** one learner's state is read into another's active context, or a
  crafted learner id escapes its namespace to read/write another's files.
- **Mitigation:** all live learner state is namespaced under
  `state/learners/<id>/`; learner ids are validated and normalised
  (`profiles.validate_learner_id` rejects separators, traversal, control chars,
  reserved names, and over-long ids). The active learner is shown in every
  command's output and every trace event. Committed examples are labelled
  `learner-example` and are never loaded into a live learner's context.
  Isolation is covered by `tests/test_profiles.py` (15 tests) and the
  `personalization` conformance evals.
- **Residual:** this is **local profile isolation, not authentication** — anyone
  with filesystem access to `state/` can read or switch any local profile. There
  is no multi-user auth or hosted tenancy.
- **Planned:** authenticated multi-tenant profiles if Packet Lab is ever hosted.

## What is explicitly out of scope

- Defending against a host that is already compromised.
- Defending against the operator, who owns the machine and the repository.
- Cryptographic integrity of traces against an attacker with write access to
  `state/` and the ability to recompute the chain — the chain detects
  accidental or lazy tampering and out-of-band edits, not a determined forger
  who reruns `verify_chain`'s algorithm. (Signed provenance is the planned
  upgrade.)
