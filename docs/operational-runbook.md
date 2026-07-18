# Operational Runbook

How to install, run, drive, inspect, and troubleshoot the Packet Lab control
plane. This is the operator's view: which commands exist, what a lesson
session looks like on the CLI, where state lives on disk, and what to do when
something breaks.

Architecture in one paragraph, so the rest of this document reads correctly:
Packet Lab is one reasoning agent (the Claude Code assistant, governed by
`AGENTS.md`) plus a deterministic control plane in `packetlab/lab/`. The
agent does the judgment work — planning lessons, designing experiments,
explaining protocols. The control plane owns safety, state, budgets, and
observability, and it is plain Python: there is no in-repo LLM call and no
separate agent processes. Role names you may see in artifacts (Tutor,
Experiment Designer, Tool Engineer, Reviewer) are artifact-contract
conventions for that single agent, not separate processes. Command execution
goes through a restricted runner (rlimits + process-group kill + scrubbed
environment) — deliberately **not** called a sandbox, because it is not an
isolation boundary. The enforcement is two-tier: for generated tools and
guarded subprocesses the boundary is physically enforced (they actually run
under the restricted runner after policy checks); for the agent itself, which
has repo write access, the boundary is procedural and audit-detectable — every
guarded action lands in a hash-chained trace, and `inspect --verify` flags
tampering after the fact rather than preventing it.

## Prerequisites

- Linux. The lessons are about Linux networking; the runner uses `resource`
  rlimits and `/proc`, so other platforms are out.
- Python 3.10+. The control plane is stdlib-only.
- `tcpdump`, with the packet-capture capability granted once:

  ```bash
  sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/tcpdump
  getcap /usr/bin/tcpdump   # verify it took
  ```

- `python3-rich` — needed **only** for the live packet viewer
  (`scripts/packetlab.py`). Every control-plane command works without it.

  ```bash
  sudo apt install python3-rich
  ```

## Install and first run

```bash
git clone <repo-url> packet-lab
cd packet-lab
./packet-lab.sh doctor    # health check: doc caps + curriculum/ROADMAP consistency
./packet-lab.sh test      # 163 unit tests over the safety mechanisms
./packet-lab.sh eval      # 54 control-plane conformance evals
./packet-lab.sh demo      # scripted end-to-end run with real command execution
```

All four should pass on a fresh clone. `demo --failure` additionally walks the
failure and recovery paths (denied commands, budget stops) — useful to see
what a refusal looks like before you hit one in a real lesson.

## Command map

`./packet-lab.sh` is a thin passthrough to `python3 -m packetlab.lab` plus two
conveniences (`test`, `viewer`). There is deliberately no second command
surface to drift out of sync — anything not listed below is forwarded to the
Python CLI verbatim.

| Command | What it does |
|---|---|
| `./packet-lab.sh doctor` | Doc size caps, curriculum/ROADMAP consistency, terminology check. Exit 1 on any FAIL. |
| `./packet-lab.sh test` | `python3 -m unittest discover -s tests` — the 163 safety-mechanism tests. |
| `./packet-lab.sh eval` | The 54 conformance evals (`evals/run_evals.py`). |
| `./packet-lab.sh demo [--failure]` | Scripted end-to-end run; `--failure` demonstrates denial/recovery paths. |
| `./packet-lab.sh viewer [mode] [iface]` | Live tcpdump-backed viewer (`scripts/packetlab.py`). Modes: `icmp` (default), `arp`. Needs `python3-rich`. |
| `./packet-lab.sh <anything else>` | Forwarded to `python3 -m packetlab.lab`. |

The Python CLI subcommands (`python3 -m packetlab.lab ...`, or via the
wrapper):

| Subcommand | Purpose |
|---|---|
| `learner create <id> [--name N]` | Create a local learner profile (validated id). The first profile becomes active automatically. |
| `learner list` | List local profiles and show which is active. |
| `learner use <id>` | Set the active learner. All lesson/record/run/tool/inspect commands act on the active learner. |
| `learner show [--concept <id>]` | Show the active learner's mastery summary (or one concept). |
| `learner reset [<id>] --force` | Wipe a learner's progress (defaults to active); `--force` is required because it is destructive. |
| `lesson start <lesson-id>` | Start a lesson (e.g. `v1.1`) **for the active learner**; mints a run id, creates the trace and workspace. Refuses planned lessons and refuses if another lesson is still open. |
| `lesson status` | Current lesson state: concept phases, counters vs budgets, stop reasons. |
| `lesson close --confirm "<criterion>"` | Close the lesson. Every completion criterion in `curriculum/curriculum.json` must be confirmed verbatim (repeat `--confirm`). |
| `lesson abort --reason "<why>"` | Abort the lesson explicitly; the reason is recorded. |
| `record prediction\|observation\|explanation\|skip <concept> --text "..."` | Record learner evidence; the governor gates phase order per concept. |
| `run --category <cat> [--timeout N] [--observation-concept <id>] -- <argv...>` | Run a guarded command through governor evaluate → policy check → restricted runner → governor commit. `--observation-concept` records the observation in the governor phase and the learner model together. |
| `experiment validate --spec <file>` | Validate a structured experiment spec and cross-check every step's argv against the command policy before anything runs. |
| `tool lookup\|validate\|invoke\|list\|cleanup` | Generated-tool lifecycle (spec validation, AST check, tests, registry, invocation). |
| `learner show [--concept <id>]` / `learner reset` | Inspect or reset the concept-level learner model. |
| `inspect [<run-id> \| --file <trace>] [--timeline] [--verify]` | Dump, summarize, or hash-verify a run trace (a live run id or a committed trace file). |
| `doctor` / `demo` / `eval` | Same as the wrapper forms above. |

Command categories accepted by `run --category` (defined in
`packetlab/lab/policy.py`): `observe_network`, `dns_query`, `ping`,
`capture`, `read_system_file`, `modify_neighbour_cache`. Each lesson permits
only a subset (`permitted_categories` in `curriculum/curriculum.json`), and
within a category only allowlisted binaries with checked flags run at all.

## A worked lesson session

Everything goes through the CLI so every step lands in the run trace. A
session for lesson `v1.1` (ICMP fundamentals), working the concept
`icmp.echo-request-reply`:

```bash
# 0. Select a learner (once per engineer). The first profile becomes active;
#    switch any time with `learner use <id>`. The active learner appears in
#    every command's output so you never update the wrong profile.
./packet-lab.sh learner create engineer-a
# => {"created": "engineer-a", "display_name": "engineer-a", "active": true}

# 1. Start — mints a run id, opens the trace, creates the workspace, all under
#    state/learners/engineer-a/.
./packet-lab.sh lesson start v1.1
# => {"learner": "engineer-a", "started": "v1.1", "run_id": "run-20260717-...", "objective": "..."}

# 2. Record a prediction BEFORE running anything. The governor enforces
#    theory -> predicted -> observed -> explained per concept: you cannot
#    record an observation for a concept with no prediction (or explicit skip).
./packet-lab.sh record prediction icmp.echo-request-reply \
    --text "Each echo request will be answered by a reply sharing id and seq"

# 3. Run the experiment. --category must be permitted for this lesson, the
#    binary and flags must pass policy (ping must be count-bounded, -c <= 20),
#    and the step budget must have headroom. Everything after -- is the argv;
#    no shell is ever involved.
./packet-lab.sh run --category ping -- ping -c 3 192.168.1.1

# 4. Record what was actually observed, then the explanation.
./packet-lab.sh record observation icmp.echo-request-reply \
    --text "3 requests, 3 replies; icmp_seq 1-3 matched pairwise, same id"
./packet-lab.sh record explanation icmp.echo-request-reply \
    --text "The kernel pairs replies to requests by (id, seq); id identifies the ping process"

# 5. Check where things stand at any time.
./packet-lab.sh lesson status
./packet-lab.sh learner show --concept icmp.echo-request-reply

# 6. Close. Each completion criterion from curriculum.json must be confirmed
#    verbatim; unconfirmed criteria block the close.
./packet-lab.sh lesson close \
    --confirm "Student explains how tcpdump observes packets without being the sender or receiver" \
    --confirm "Student explains request/reply pairing via id and sequence" \
    --confirm "..."
```

Notes on the flow:

- `run` prints the command output wrapped in untrusted-data markers (the
  output of live commands is data, never instructions) and a JSON status
  line; default timeout 20 s, output capped at 200,000 bytes.
- `run --observation-concept <id> --observation-note "<text>"` records an
  observation automatically when the command succeeds — a shortcut for the
  separate `record observation` step.
- `record skip <concept>` is the "go ahead" waiver: it advances the phase
  gate but is stored as skip evidence, never as mastery. A concept reaches
  `mastered` in the learner model only with at least one observation (or
  transfer) *and* one explanation on record.
- Budgets (`max_steps`, `max_retries`, `max_generated_tools`,
  `max_execution_seconds`) are consumed on commit, after execution. When one
  runs out the governor denies further actions of that kind and records a
  stop reason visible in `lesson status`.

## Inspecting and verifying a run

Every CLI invocation during a session appends events to
`state/runs/<run-id>/trace.jsonl` — one JSON object per line, each carrying
the SHA-256 of the previous event.

```bash
# Compact timeline: seq, time, component, event, rule/status.
./packet-lab.sh inspect run-20260717-174554-33f355 --timeline

# Full event dump (JSON).
./packet-lab.sh inspect run-20260717-174554-33f355

# Recompute the hash chain end to end.
./packet-lab.sh inspect run-20260717-174554-33f355 --verify
# => {"run_id": "...", "events": N, "chain_ok": true, "problems": []}
```

`--verify` exits non-zero and lists the failing sequence numbers if any event
was edited, removed, or inserted. This is the audit-detection half of the
two-tier boundary described at the top: the agent could edit state files
directly (it has repo write access), but a silent edit breaks the chain and
the verifier flags it. Traces store summaries, not payloads — long fields are
truncated and packet contents never appear in them.

Inspecting an unknown run id prints the list of known runs. A real committed
example lives at `docs/examples/trace-icmp-v1.1.jsonl`, with its generated
tool's four artifacts (spec, source, test, provenance) in
`docs/examples/icmp-echo-summary/`.

## Where state lives

`state/` is gitignored — runtime data, never committed. All live learner state
is namespaced per learner:

| Path | Contents |
|---|---|
| `state/active-learner` | The id of the currently selected learner. |
| `state/learners/<id>/profile.json` | The learner profile: id, display name, created_at, preferences, schema version. |
| `state/learners/<id>/lesson.json` | That learner's active-lesson state: concept phases, counters, budgets, stop reasons, history. Written atomically under an flock with a generation counter. |
| `state/learners/<id>/learner.json` | That learner's concept-level model: per-concept state (`unseen`/`in_progress`/`needs_review`/`mastered`) plus evidence. |
| `state/learners/<id>/runs/<run-id>/trace.jsonl` | That learner's hash-chained traces (each event carries the learner id). |
| `state/learners/<id>/workspace/<run-id>/` | Per-run scratch directory guarded commands run in; workspace-path checks (e.g. `tcpdump -w`) resolve against it. |
| `state/learners/<id>/tools/` | That learner's generated tools + registry (learner-local; not shared). |

**Compatibility with pre-multi-learner installs:** a legacy single-user install
kept state at `state/lesson.json` + `state/learner.json`. On first use these are
migrated into a clearly named `default` learner (`state/learners/default/`) and
that learner is made active — never silently promoted to a global learner. This
is automatic and one-way; see `profiles.migrate_legacy_if_present`.

Related paths outside `state/`: the shared/built-in tool registry scaffold is
`tools/registry.json`; packet captures belong in `capture/`, which is gitignored
because captures may contain sensitive traffic.

## Crash and resume

Sessions are a series of short-lived CLI invocations, so a crash loses at
most the trace line being written. If a session dies mid-lesson, the lesson
simply remains open in the active learner's `state/learners/<id>/lesson.json`:

- `lesson status` surfaces it — `closed: false` with the original run id.
- `lesson start` for anything else refuses:
  `lesson 'vX.Y' is still active; close or abort it first`.
- To continue, just keep issuing commands: `record` and `run` reattach to the
  active run's trace automatically.
- To discard it, abort explicitly — this is the only way to clear an
  interrupted lesson:

  ```bash
  ./packet-lab.sh lesson abort --reason "session died mid-lesson; restarting"
  ```

There is no silent auto-recovery by design: an interrupted lesson requires an
explicit human decision to resume or abort, and the abort reason is recorded
in both state and trace.

## tcpdump capability caveat

`apt upgrade` replaces the `tcpdump` binary and **silently drops the setcap
capability**. If capture suddenly fails with a permission error after a
system update, check and re-apply:

```bash
getcap /usr/bin/tcpdump
# expected: /usr/bin/tcpdump cap_net_admin,cap_net_raw=eip
sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/tcpdump
```

`getcap` is allowlisted in the `observe_network` category, so this check can
be run inside a lesson and land in the trace.

## Troubleshooting

**Viewer fails with a `rich` import error.** Only the viewer needs it:
`sudo apt install python3-rich`. The viewer prints this exact hint itself.
No control-plane command depends on rich.

**`tcpdump: ... You don't have permission to capture`.** The setcap
capability is missing — see the caveat above. This is the most common
post-upgrade breakage.

**`run` says `no active lesson; run 'lesson start' first`.** Guarded commands
only execute inside a lesson so they are budgeted and traced. Start one.

**Denied with rule `category-not-permitted`.** The category is valid but not
in this lesson's `permitted_categories`. That is scope control working as
intended, not a bug — check the lesson entry in `curriculum/curriculum.json`.

**Denied with rule `predict-before-observe` (or `observe-before-explain`).**
The per-concept phase gate: record a prediction first, or record an explicit
`skip` if the student waived it.

**`ping` denied with rule `required-flag`.** Policy requires `-c` (count) so
ping terminates on its own, bounded at 20.

**`refusing to run as root`.** The restricted runner refuses euid 0
outright. Run as a normal user; tcpdump gets its capture rights from the
file capability, not from root.

**`dig`/`tcpdump` failing under thread limits — they should not be.** The
per-user process cap (`RLIMIT_NPROC` headroom) is applied **only** to
untrusted generated tools, not to trusted allowlisted binaries; `dig` and
`tcpdump` spawn threads and would trip a low cap. If a trusted command hits a
process limit, it is coming from the host (e.g. `ulimit`, systemd user
limits), not from Packet Lab — check `ulimit -u` in the invoking shell.

**`lesson close` fails with unconfirmed criteria.** Each `--confirm` value
must match a completion criterion string from `curriculum/curriculum.json`
exactly. Copy them verbatim.

**`inspect --verify` reports chain problems.** Someone or something edited
`trace.jsonl` after the fact, or a line was corrupted mid-write. The trace is
append-only evidence; do not repair it in place — treat the run as tainted
and note it in the lesson record.

**`doctor` fails.** It exits 1 on any of: a doc size hard cap breached, a
curriculum-vs-ROADMAP status or progress mismatch, or misleading plural-agent
terminology in `docs/`. The output names the exact file and problem; fix the
named file rather than the checker.
