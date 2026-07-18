# The learner model

`packetlab/lab/learner.py` tracks what the student actually knows, per
**concept** (a node in the curriculum graph, e.g. `dns.udp-53`), not per
lesson. It is a deliberately small state machine over a deliberately rich
evidence log, persisted in `state/learner.json`.

Two design decisions drive everything below:

1. **Few states, rich evidence.** Packet Lab paces at roughly one question per
   concept per session. A ten-rung mastery ladder would demand more
   measurement events than the pacing produces, so the ladder would either
   stall or get climbed on thin air. Instead there are four states, and the
   nuance lives in the append-only evidence list attached to each concept.
2. **Every state change is evidence-backed and cites its source.** Each entry
   names the lesson and run it came from, so a claim in the learner model can
   be checked against the committed lesson narrative and the hash-chained run
   trace.

## The four states

| State | Meaning |
|---|---|
| `unseen` | No evidence recorded for the concept. |
| `in_progress` | Some evidence exists, but the mastery bar is not met. |
| `needs_review` | An evaluator note flagged the concept; reachable from **any** state. |
| `mastered` | Grounded evidence **and** an explanation exist (see the rule below). |

The nominal path is `unseen → in_progress → mastered`, with `needs_review`
reachable from anywhere via `mark_needs_review()` (which records an
`evaluator_note` entry whose summary starts with `needs review:`).

## Evidence entries

Every call to `LearnerModel.add_evidence()` appends one entry:

```json
{
  "ts": "2026-07-17T17:46:09+00:00",
  "kind": "prediction",
  "summary": "first dig hits the radio (cache miss), second is silent (stub cache hit over lo)",
  "lesson_id": "v3.0",
  "run_id": "run-20260717-174554-33f355"
}
```

- `kind` must be one of `introduction`, `prediction`, `observation`,
  `explanation`, `transfer`, `skip`, `evaluator_note` — anything else raises
  `ValueError`.
- `summary` is truncated to 500 characters (`MAX_EVIDENCE_SUMMARY`).
- `lesson_id` and `run_id` tie the entry to a lesson doc and a hash-chained
  trace under `state/runs/<run_id>/trace.jsonl`.

Evidence normally arrives through the CLI, which routes it past the Curriculum
Governor's phase gates first:

```bash
python3 -m packetlab.lab record prediction dns.udp-53 --text "..."
python3 -m packetlab.lab record observation dns.udp-53 --text "..."
python3 -m packetlab.lab record explanation dns.udp-53 --text "..."
# or, attached directly to a guarded command:
python3 -m packetlab.lab run --category dns_query \
    --observation-concept dns.udp-53 --observation-note "..." -- dig example.com
```

## The state rule: `_derive_state`

State is never set directly. After each append, `_derive_state(evidence)` — a
pure function of the evidence list alone — recomputes it:

1. If the most recent `needs review` evaluator note has **no** later
   `observation`/`explanation`/`transfer` entry, the state is `needs_review`.
   The flag persists until new grounded work supersedes it.
2. Otherwise, `mastered` iff the concept has at least one **grounding** entry
   (`observation` or `transfer`) **and** at least one `explanation`. Theory
   alone (`introduction` + `prediction`) can never reach mastery, and neither
   can an explanation without an observation behind it.
3. Otherwise, `in_progress` — with one carve-out: `skip` entries are excluded
   from that check, so a concept whose only evidence is skips does not read
   as progress. A skip waiver (the student says "go ahead") satisfies the
   governor's phase gate and is recorded honestly as a skip; it **never**
   contributes to mastery.

Because the function is pure and the evidence is append-only, the state is
reproducible: replay the evidence list and you get the same state. The rule is
pinned by tests in `tests/test_specs_learner_untrusted.py`
(`LearnerMastery.test_theory_alone_is_not_mastery`,
`test_observation_plus_explanation_is_mastery`,
`test_skip_does_not_grant_mastery`, `test_evidence_is_retained`).

## What is persisted — and what is not

Everything lives in `state/learner.json`:

```json
{
  "version": 1,
  "generation": 1,
  "concepts": {
    "dns.udp-53": {
      "state": "in_progress",
      "evidence": [ ... entries as above ... ],
      "updated_at": "2026-07-17T17:46:09+00:00"
    }
  }
}
```

Writes go through `statefile.update_json`: `flock` exclusive lock, mutate,
generation bump (a stale write raises `StaleStateError` instead of silently
clobbering), atomic replace. `ConceptState` returned to callers is a frozen
dataclass.

What is **not** stored: no name, no account, no timing analytics, no free-form
transcript — nothing about the person beyond the concept-evidence summaries
themselves. The file is plain human-readable JSON, so "export" is trivial and
inspection needs no tooling:

```bash
python3 -m packetlab.lab learner show                       # per-state counts
python3 -m packetlab.lab learner show --concept dns.udp-53  # full evidence
python3 -m packetlab.lab learner reset                      # wipe to empty
```

There is no dedicated `export` subcommand; `learner show` emits JSON and
`state/learner.json` itself is the portable artifact.

## The seed is real history

The current `state/learner.json` was not fabricated to look plausible. Its
entries were written live by the control plane during actual sessions: the
`dns.udp-53` prediction above cites lesson `v3.0` and run
`run-20260717-174554-33f355`, and the same prediction appears, in the
student's words, in the committed session narrative
`docs/lessons/v3.0-dns.md`. That cross-reference is the point — a reviewer
audits the learner model by diffing each evidence summary against the lesson
docs (`docs/lessons/v1.1-icmp-fundamentals.md` through `v3.0-dns.md`) and the
run traces, not by trusting the JSON.

## Honest limitation: who grades mastery?

Mastery in this system is **asserted by the same agent that teaches**. There
is one reasoning agent; the "Tutor" that explains a concept and the judgment
that a student's explanation earns an `explanation` evidence entry are the
same process. There is no independent grader, no second model, and no
model-graded eval behind the `mastered` state.

What the design provides instead is **auditability**, not independence:

- Every mastery claim decomposes into concrete evidence entries with
  timestamps, lesson IDs, and run IDs.
- The deterministic `_derive_state` rule means the control plane — not the
  agent's prose — decides whether the evidence set clears the bar.
- A human reviewer can diff each summary against the committed lesson
  narratives in `docs/lessons/*.md` and the hash-chained traces
  (`inspect <run_id> --verify`) to check that claimed observations actually
  happened in a recorded run.

**Planned:** a separate-model evaluator that grades student explanations
independently of the tutoring agent. It is a roadmap item, not a current
capability, and nothing in the codebase should be read as providing it today.


## Multi-learner isolation and teaching adaptation

Each engineer has an isolated model under `state/learners/<id>/learner.json`; a
new learner starts empty and never inherits another's mastery (see
`tests/test_profiles.py`). Lesson selection is driven by the active learner's
own mastery over the shared curriculum graph — a deterministic graph plus
per-learner mastery, not a statistical recommender.

What the tutor can adapt on **today** (all derivable from the learner's
evidence): mastered prerequisites (skip already-mastered concepts), unseen or
`needs_review` concepts (target them), and unfinished lessons (resume them).
Signals that are **recorded but not yet used for automated recommendation**
(Planned): previous incorrect predictions, hint usage, and demonstrated
transfer ability. Mastery remains assistant-asserted and evidence-audited; no
independent grader exists (Planned).
