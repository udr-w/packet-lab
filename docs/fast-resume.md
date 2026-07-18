# Fast Resume

Why "resume lesson" answers in seconds, and what is (deliberately) not done
at resume time.

## The problem this solves

The first real learner resume took ~213 s to the first useful teaching
response. Profiling showed the repository's own shell commands cost under a
second each; the latency was **turn count**: the old AGENTS.md startup
procedure forced a doctor run, seven document reads (~54 KB), several CLI
status calls, and a live DNS capture — roughly twenty sequential
assistant-tool round-trips, each paying full model latency, before the
learner saw anything.

## Architecture

One read-only command replaces the sweep:

    ./packet-lab.sh resume            # learner view (default)
    ./packet-lab.sh resume --json     # machine-readable snapshot
    ./packet-lab.sh resume --verbose  # learner view + operator diagnostics

`packetlab/lab/resume.py` builds the snapshot from canonical state only:
the active learner's `lesson.json` + `learner.json` plus the shared
curriculum. It returns learner, lesson, where they stopped, any open
prediction, the ONE next action, and a private-preflight recommendation.

Guarantees (pinned by `tests/test_resume.py`):

- read-only — no run creation, no migration, no mastery/governor writes;
- no network, no subprocesses (so no tcpdump/dig/ping/getcap, no doctor,
  no tests/evals);
- reads only the **active** learner's directory — never another learner's
  evidence, never committed examples under `docs/examples/`;
- clear statuses: `resume`, `fresh`, `no_active_learner`, `all_complete`.

There is no derived progress cache: the snapshot reads the two small
canonical JSON files directly (warm ~1 ms, cold process ~45 ms — see the
benchmark), so a cache would add staleness risk for no measurable benefit.

## Canonical learner state

The control plane (`state/learners/<id>/`) is the single source of truth
for lesson progress. Assistant chat memory is never authoritative for
mastery, predictions, phases, or curriculum position; when memory and the
snapshot disagree, the snapshot wins. A fresh session with a valid active
learner must never open with "no memory of a previous lesson".

## Learner mode vs repository-owner mode

Defined in AGENTS.md (Operating Modes). Learner mode — the default for
lesson requests — acknowledges immediately, makes one snapshot call, and
teaches; it never runs doctor/tests/evals or reads the documentation sweep.
Repository-owner mode (engineering work) keeps the full startup: lab-doctor
plus README/ROADMAP/TASK/handover reads. Learner mode never pays
repository-owner costs.

## Private preflight

`packetlab/lab/preflight.py` decides — deterministically, from the lesson's
permitted command categories and the learner's next phase — whether any
environment validation is worth doing before the learner is asked to
predict. Outcomes: `none_needed`, `capability_only` (binary/capability
presence, no packets), `lightweight` (adds one disposable representative
probe), `unavailable` (a required check failed).

    ./packet-lab.sh preflight [--json]   # PRIVATE operator output

The executor runs presence/capability checks only. A representative live
probe (e.g. one `dig`) remains an explicit assistant action, guided by the
plan and bound by its contamination controls.

### Non-contamination

Preflight must not consume or warm the phenomenon the learner is about to
observe. For DNS the plan carries a **disposable hostname** — a random label
under example.com that cannot collide with any name reserved for the
learner — and lists the learner's targets as forbidden. Live probes are
deferred until after the learner's prediction is recorded, immediately
before their experiment. Preflight results are never learner evidence, never
advance mastery or phase, and are never shown to the learner by default.

Residual risks are declared in the plan rather than hidden: a probe still
exercises the resolver path (leaving a negative-cache entry for the
disposable label) and advances interface counters. Not all state can be
restored perfectly; the design isolates rather than pretends to undo.

### Limitations of hidden verification

Preflight proves the *path* works (tools present, capability intact,
resolver answering), not that the learner's experiment will show the
expected result. When validation contradicts a lesson's assumptions, the
assistant reports the mismatch honestly instead of inventing expected
results — see `learner_message_for_failure`.

## Output separation

Default output is for the learner: welcome, lesson, where they stopped, one
next step — no run IDs, state paths, capability strings, or control-plane
vocabulary. `--verbose` appends operator diagnostics (state source, run ID,
phases, preflight plan) under an explicit "not for the learner" banner.
`--json` is the machine surface, schema-checked by `validate_snapshot`.

## Lazy validation policy

- **At resume**: active-learner lookup, learner-state read, curriculum
  lookup, unfinished-step calculation, preflight decision. Nothing else.
- **Private preflight (only when recommended)**: the planned checks, and at
  most one disposable representative probe.
- **Immediately before the learner's experiment**: any remaining
  lesson-specific checks.
- **After repository changes**: doctor, tests, evals, demo — engineering
  work, never lesson-resume work.

## Performance targets

`scripts/bench-resume.py` (runs in CI, no LLM call) benchmarks warm and
cold-process snapshots across three learner shapes plus the preflight
checks. Thresholds are coarse and stable: cold snapshot FAIL > 3 s, warn
> 1 s; warm FAIL > 1 s. Measured on the reference machine: warm ~1 ms
median, cold process ~45 ms, capability preflight ~3 ms. The remaining
resume latency budget is model latency (one acknowledgement turn + one
snapshot turn + the teaching reply), outside repository control.
