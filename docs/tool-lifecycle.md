# Generated Tool Lifecycle

Packet Lab lets its single reasoning agent propose small Python tools (parsers, summarisers) when a lesson needs one. The agent writes the code; the deterministic control plane in `packetlab/lab/toolgen.py` owns everything that happens to that code afterwards: validation, testing, registration, invocation, and retirement. This document walks the lifecycle end to end, using the real registered example in `docs/examples/icmp-echo-summary/`.

## Why generated tools are untrusted

A generated tool is code written by a language model mid-lesson. It has not been reviewed by a human, and its author (the agent) also processes untrusted data — command output, packet captures, file contents — that could steer what it writes. So the control plane treats every generated tool as untrusted software from creation to retirement, regardless of how plausible it looks.

Two different boundaries apply, and it is important not to conflate them:

- **For the generated tool itself, the boundary is physically enforced.** The tool's bytes are AST-validated before anything runs, and it only ever executes under the restricted runner (`runner.py`): wall-clock deadline as the primary control, `RLIMIT_CPU`/`RLIMIT_AS`/`RLIMIT_FSIZE`/`RLIMIT_NPROC` as backstops, a fully scrubbed environment, refusal to run as root, and process-group `SIGKILL` on any overrun. The tool cannot opt out of any of this.
- **For the agent, the boundary is procedural and audit-detectable, not physical.** The agent has repo write access, so nothing physically stops it from writing a file into `tools/generated/` by hand and skipping `toolgen`. What makes that detectable rather than invisible: every legitimate lifecycle step emits hash-chained trace events (`trace.py`), registration writes a full provenance record, and `inspect --verify` checks the chain. A tool with no `tool_registered` trace event or a provenance/checksum mismatch is an audit finding, not a silent success.

The restricted runner is deliberately **not** called a sandbox. It is resource limits + process-group kill + a scrubbed environment. There are no namespaces, no seccomp, and no network cut-off. See [Honest limitations](#honest-limitations) below.

## Lifecycle at a glance

| Stage | Function | What it guarantees |
|---|---|---|
| 1. Lookup | `toolgen.lookup()` | Reuse before generation; quarantined tools never match |
| 2. Validate | `toolgen.validate()` | Size cap, encoding checks, capability policy, AST allow-list — on the exact bytes; sha256 recorded |
| 3. Test | `toolgen.run_tests()` | Unit tests pass in a fresh temp copy, after a TOCTOU sha256 re-check, under the restricted runner |
| 4. Register | `toolgen.register()` | Refuses failed validation/tests; writes registry entry + provenance record |
| 5. Invoke | `toolgen.invoke()` | Typed inputs, path policy, sha256 re-verify, restricted execution, schema-checked outputs; structured failure, never partial data |
| 6. Retire | `toolgen.cleanup()` / `toolgen.quarantine()` | Lesson-scoped tools removed when the lesson ends; unsafe tools quarantined |

## 1. Reuse before generation: `lookup()`

Generation is the last resort, not the first move. Before proposing new code, the agent calls `lookup(purpose_keywords)`, a deterministic keyword search over `tools/registry.json`. Each registered tool's `purpose`, `tags`, and `tool_id` are matched against the keywords and results are returned sorted by match score. Tools with `status: "quarantined"` are skipped — a quarantined tool cannot be rediscovered and reused by accident.

Only when no adequate tool exists does the agent write a `ToolSpec` and source for a new one.

## 2. The ToolSpec schema

Every tool is described by a typed spec (`specs.py: ToolSpec`), validated by `ToolSpec.from_dict()` before anything executes. Validation is **strict: unknown keys are errors**. This is deliberate — if unknown keys were silently ignored, the agent could smuggle fields past review that a future version of the code might start honouring, and a reviewer reading a spec could not trust that what they see is the whole contract.

| Field | Constraint |
|---|---|
| `id` | `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, max 64 chars |
| `version` | optional integer, 1–10 000 (defaults to 1) |
| `purpose` | non-empty string — what `lookup()` searches |
| `lesson_id` | `^v\d+\.\d+$` — ties the tool to a lesson |
| `inputs` | up to 20 named fields; types `string`, `integer`, `number`, `boolean`, `path`; every `path` input **must** declare `access: read` (write paths do not exist) |
| `outputs` | same field schema, no `access` key allowed; at least one output required |
| `capabilities.commands` | list; policy rejects any non-empty value — generated tools may not run external commands |
| `capabilities.filesystem.read` / `.write` | glob lists, checked against policy (see below) |
| `capabilities.network` | must be `"none"` — the only accepted value; generated tools get no network, full stop |
| `limits.timeout_seconds` | 1–30 |
| `limits.max_output_bytes` | 1–1 000 000 |
| `dependencies.python` | only `"standard-library-only"`; third-party packages are rejected at the spec level |
| `retention` | `lesson`, `archive`, or `keep` |

### Real example: `docs/examples/icmp-echo-summary/spec.json`

This is the actual spec of a registered tool from lesson v1.1 (ICMP echo), verbatim:

```json
{
  "capabilities": {
    "commands": [],
    "filesystem": {
      "read": [],
      "write": []
    },
    "network": "none"
  },
  "dependencies": {
    "python": [
      "standard-library-only"
    ]
  },
  "id": "icmp-echo-summary",
  "inputs": {
    "ping_output": {
      "type": "string"
    }
  },
  "lesson_id": "v1.1",
  "limits": {
    "max_output_bytes": 100000,
    "timeout_seconds": 5
  },
  "outputs": {
    "loss_percent": {
      "type": "number"
    },
    "received": {
      "type": "integer"
    },
    "transmitted": {
      "type": "integer"
    }
  },
  "purpose": "Summarise ping echo request/reply counts from ping stdout",
  "retention": "lesson",
  "version": 1
}
```

Note the shape of a typical generated tool: it takes ping's stdout as a plain string, returns three typed numbers, and requests **nothing** — no commands, no filesystem, no network. Most generated tools should look like this: pure text-in, JSON-out parsers.

## 3. The validation pipeline: `validate()`

`validate(spec, source, test_source, workspace, permitted_categories)` runs every check and returns a structured findings record (the same record you can read later under `validation` in the tool's provenance). The checks:

1. **Size cap.** Tool source and test source must each be under 200 000 bytes (`MAX_TOOL_SOURCE_BYTES`). Oversized source short-circuits everything else.
2. **Encoding-trick rejection, on the exact bytes.** `astcheck.reject_encoding_tricks()` reads the raw bytes that will later execute — not a decoded string — and rejects a UTF-8 BOM, any non-UTF-8 PEP 263 coding cookie, and bytes that do not decode as UTF-8. The point: a coding cookie or BOM can make CPython execute different source than a str-level validator saw. Validating the exact bytes closes that gap.
3. **Capability check.** `policy.check_capabilities()` enforces the generated-tool stance: network must be `"none"`, `commands` must be empty (guarded commands go through the lesson runner, never through a generated tool), every write glob must resolve inside the lesson workspace, and every read glob must be inside the workspace **or** on the readable-system-file allowlist (`/etc/resolv.conf`, `/proc/net/*`, `/sys/class/net/*`, …). Glob patterns containing `..` are rejected outright.
4. **AST validation of the source** (`astcheck.validate_source()`) — see below.
5. **AST validation of the test file too**, with `is_test=True`. A malicious test file would otherwise be a trivial bypass, since tests execute. Test files get exactly two extra permitted imports: `unittest` and `tool` (the module under test).
6. **sha256 recorded.** The validator computes and records `source_sha256` and `test_sha256` of the exact validated bytes. Everything downstream — test execution, registration, every future invocation — is pinned to these hashes.

### The AST check: allow-by-exception

`astcheck.py` walks the full AST (`ast.walk`, so annotations, decorators, defaults, lambda and comprehension bodies are covered, not just top-level statements) and collects **every** violation rather than stopping at the first. The stance is allow-by-exception:

- **Imports:** only this standard-library allowlist —
  `json`, `sys`, `re`, `math`, `statistics`, `collections`, `dataclasses`, `datetime`, `ipaddress`, `struct`, `itertools`, `functools`, `typing`, `argparse`, `textwrap`, `string`, `enum`, `decimal`, `fractions`, `bisect`, `heapq`, `unicodedata`, `base64`, `binascii`, `hashlib`.
  Everything else is rejected, explicitly including `os`, `subprocess`, `socket`, `shutil`, `ctypes`, `importlib`, `threading`, `multiprocessing`, `signal`, `resource`, `pty`, `tempfile` — and `pathlib`, whose `read_text`/`write_text`/`unlink` methods would bypass the `open()` gate.
- **Forbidden names:** `eval`, `exec`, `compile`, `__import__`, `globals`, `vars`, `locals`, `getattr`, `setattr`, `delattr`, `breakpoint`, `input`, `help`, `memoryview`, `exit`, `quit`, `copyright`, `credits`, `license`.
- **Forbidden attributes:** the `str.format` / `format_map` reflection channel; pathlib filesystem methods (`read_text`, `write_text`, `read_bytes`, `write_bytes`, `unlink`, `rmdir`, `mkdir`, `rename`, `replace`, `chmod`, `symlink_to`); and process-spawning names (`system`, `popen`, `spawn`, `fork`, `exec`).
- **Dunder attribute access** (`__globals__`, `__subclasses__`, `__class__`, `__mro__`, `__dict__`, …) is rejected wherever it appears in the tree — this is the classic escape route from a name-level blocklist.
- **`open()` is gated, even for reads.** The path must be a string literal (no computed paths) and the mode a string literal. A relative path is acceptable (it resolves under the workspace at run time, because the runner sets `cwd` to the workspace); an absolute or `~` path must match a declared read/write capability glob. Any write/append/exclusive mode (`w`, `a`, `x`, `+`) requires a declared write capability. Read mode is gated too, precisely because there is no OS-level filesystem confinement underneath.

## 4. Test execution: `run_tests()`

Registration requires passing tests, and the tests run under the same restrictions as the tool will:

1. **TOCTOU re-check first.** The sha256 of the source and test bytes about to run is compared against the hashes recorded at validation. Any mismatch returns `refused` — "source changed since validation" — before a single line executes.
2. **Fresh temp copy.** The bytes are written into a clean `.test-<tool_id>` directory inside the workspace (removed and recreated if it exists, deleted afterwards). Tests never run against the registry copy or any directory the agent has been editing in.
3. **Restricted runner.** `python3 -m unittest test_tool -v` runs via `run_restricted()` with `limit_processes=True`, a timeout of the spec's `timeout_seconds` + 10, and a 200 000-byte output cap. That means: scrubbed environment (no inherited `PATH` or secrets; `HOME` pointed at the temp directory), rlimits applied, wall-clock deadline enforced by the parent, and process-group kill on overrun.

A failing, timing-out, or unvalidated test blocks registration — `register()` raises rather than persisting anything.

## 5. Registration and provenance: `register()`

`register()` refuses to persist a tool whose validation record is not `ok` or whose tests did not return `ok`. On success it writes four files under `tools/generated/<tool_id>/` — `tool.py`, `test_tool.py`, `spec.json`, `provenance.json` — and upserts an entry in `tools/registry.json` (tool id, path, purpose, derived tags, status, retention, lesson id). A `tool_registered` event is emitted into the hash-chained trace.

`provenance.json` is the record a reviewer reads to answer *"why did this tool exist and what did it do?"*. It contains:

| Field | Content |
|---|---|
| `tool_id`, `version`, `lesson_id`, `created_at`, `generator` | Identity and origin |
| `source_sha256`, `test_sha256` | The pinned checksums of the validated bytes |
| `requested_capabilities` | Exactly what the spec asked for |
| `approved_capabilities` | What policy actually granted — commands always `[]`, network always `"none"`, so the requested/approved diff is visible at a glance |
| `dependencies` | `["standard-library-only"]` |
| `validation` | The full findings record from `validate()` — every check and its errors (empty lists when clean) |
| `test_results` | The runner summary of the unittest run: status, exit code, duration, output sizes, truncation flags |
| `executions` | Append-only history: timestamp, run id, status, duration of every invocation |
| `retention`, `status` | Lifecycle state (`registered` or `quarantined`) |

The real example is `docs/examples/icmp-echo-summary/provenance.json`: validation checks all empty (clean), tests `ok` in 37 ms, one recorded execution (`run-example-icmp-v1-1`, 19 ms, `ok`), and matching sha256s in both the top-level fields and the embedded validation record. The corresponding hash-chained trace for that lesson run is `docs/examples/trace-icmp-v1.1.jsonl`.

## 6. Invocation: `invoke()`

Every call goes through the same gauntlet; there is no fast path:

1. **Registration check** — no provenance record, no run (`not_registered`).
2. **Quarantine check** — quarantined tools refuse to run (`quarantined`).
3. **Spec re-parse** — the on-disk `spec.json` is re-validated through the strict parser (`bad_spec` on failure).
4. **sha256 re-verify** — the on-disk `tool.py` bytes are hashed and compared to `source_sha256` in provenance. Any drift — whether from tampering or an honest edit that skipped the lifecycle — is `checksum_mismatch`, and the tool does not run.
5. **Typed input validation** — inputs are checked strictly against the spec's input schema: undeclared fields rejected, declared fields required, every value type-checked (`bad_inputs`).
6. **Path-input policy check** — every input declared as `type: path` is passed through `policy.check_path_input()`: the value is resolved (symlinks followed) and must match one of the tool's declared read-capability globs (`bad_input_path`). A tool with no declared read globs — like `icmp-echo-summary` — can never receive a path at run time.
7. **Restricted execution** — `python3 tool.py` under `run_restricted()` with the spec's own `timeout_seconds` and `max_output_bytes`, `limit_processes=True`, `cwd` set to the lesson workspace, and the inputs delivered as a single JSON object on stdin. The tool writes a single JSON object to stdout.
8. **Defensive JSON parse** — stdout is parsed with a size guard and with `NaN`/`Infinity` constants rejected; anything unparseable is `bad_output`, never a crash.
9. **Output-schema validation** — the parsed object is checked strictly against the spec's declared outputs: missing fields, undeclared fields, or wrong types are `schema_violation`.

The result is always a structured record — `{"tool_id", "status", "run", ...}` — where `status` is one of `ok`, `not_registered`, `quarantined`, `bad_spec`, `checksum_mismatch`, `bad_inputs`, `bad_input_path`, `execution_failed`, `bad_output`, `schema_violation`. **On any failure the caller gets the failure and nothing else — never partial data** that could be mistaken for real observations in a lesson. Each invocation is appended to the provenance `executions` history and emitted as a `tool_invoked` trace event.

## 7. Retention, quarantine, cleanup

Retention is declared in the spec and enforced by `cleanup()`:

- **`lesson`** — the tool exists for one lesson. `cleanup(lesson_id)` removes the tool directory and its registry entry when the lesson ends, and emits a `tools_cleaned_up` trace event. This is the right default (and is what `icmp-echo-summary` declares).
- **`archive`** and **`keep`** — the tool survives lesson cleanup. The distinction between the two is declarative today: `cleanup()` only ever removes `lesson`-retention tools.

`quarantine(tool_id, reason)` is the kill switch: it flips `status` to `quarantined` in both the provenance record and the registry, records the reason, and emits a `tool_quarantined` trace event. From that point the tool is invisible to `lookup()` and refused by `invoke()`. Quarantine deliberately does **not** delete the files — the evidence stays on disk for review.

## Honest limitations

Stated plainly, because the design depends on you knowing them:

- **AST validation reduces risk; it does not prove safety.** It is a static allow-by-exception filter over one Python file. It blocks the obvious and the classic-clever (encoding tricks, dunder escapes, reflection channels, pathlib bypasses), and it collects every violation for the provenance record — but a determined novel construction is not provably impossible. That is why it is layer one, not the whole defence.
- **The restricted runner is the backstop, not a sandbox.** Wall-clock deadline, rlimits, scrubbed environment, no-root, process-group kill. No namespaces, no seccomp, no network cut-off, no OS-level filesystem confinement. It bounds blast radius (time, memory, processes, file size, output) and guarantees no lingering children; it is not an isolation boundary.
- **A validated tool could still open a file readable by the invoking user** — there is no OS-level FS sandbox to stop it. This is exactly why the capability globs and the AST `open()` gate matter: `open()` paths must be string literals, relative paths are confined to the workspace by `cwd`, absolute paths must match declared read globs checked against the workspace + system-file allowlist, and runtime path inputs are re-checked against policy with symlinks resolved. The gate is enforced at validation and invocation because the OS will not enforce it at run time.
- **For the agent, the lifecycle is procedural.** The agent has repo write access and could write into `tools/generated/` directly. The mitigations are audit-shaped, and they work: `invoke()`'s sha256 re-verify refuses anything whose bytes don't match a provenance record, and the hash-chained trace (`inspect --verify`) makes a registration that never emitted `tool_registered` a detectable anomaly rather than a silent one.

## Generated tools are learner-local

Generated tools are stored per learner under `state/learners/<id>/tools/` and
are validated, tested, and invoked in that learner's own space. **A tool that
succeeded for one learner is not automatically trusted for another** — it does
not enter a global registry merely because it passed once. The repo-level
`tools/registry.json` is a shared, built-in registry scaffold; promoting a
learner-local tool into it (recording originating lesson, validation version,
capability policy, test evidence, checksum, and an anonymized source reference —
never the raw learner identity) is a **Planned** reviewed step, not automatic.
Provenance stored today carries no learner id (verified by
`tests/test_profiles.py::test_13`).

The lifecycle is covered by the repository's test and eval suites (96 unit tests, 32 conformance evals, all passing; run the evals with `python3 -m packetlab.lab eval`).
