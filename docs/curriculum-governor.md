# The Curriculum Governor: structured goal integrity

The Curriculum Governor (`packetlab/lab/governor.py`) is how Packet Lab keeps
the tutoring agent on-goal without relying on a prompt. Drift prevention here
is a state machine plus scope and budget checks — deterministic code with unit
tests and conformance evals — not an instruction the agent is asked to follow
and might paraphrase away. Before any lesson action happens, the Governor
answers one question: *is this action inside the structured intent of the
active lesson?*

One honesty note up front. The agent has repo write access, so for the agent
itself the Governor is a **procedural** boundary: the agent is required to
route actions through `evaluate`/`commit`, and because every decision lands in
the hash-chained trace (`packetlab/lab/trace.py`, checkable with
`inspect --verify`), bypassing it is **audit-detectable** rather than
physically impossible. Physical enforcement in this system applies one layer
down — generated tools and guarded subprocesses actually run under the
restricted runner (rlimits + process-group kill + scrubbed env, which is not a
sandbox or isolation boundary). The Governor's value is that goal integrity is
*checkable*: every allow/deny is a typed `Decision` with a rule id, emitted to
a tamper-evident log.

## Lesson state: `state/lesson.json`

`start_lesson` materialises the lesson's intent from the curriculum into a
single state file. Fields:

| Field | Meaning |
|---|---|
| `generation` | Monotonic counter maintained by `statefile.py` (flock + atomic rename); stale writes raise instead of silently clobbering |
| `lesson_id`, `objective` | The active lesson and its objective, copied from `curriculum.json` |
| `run_id`, `started_at` | Which trace run this lesson belongs to, and when it began |
| `closed` (+ `closed_at`, `aborted`) | Lifecycle flags; a new lesson cannot start while another is open |
| `concept_phase` | Map of every lesson concept to its current phase, initialised to `"theory"` |
| `counters` | `steps`, `retries`, `generated_tools`, `execution_seconds` — consumed budget |
| `budgets` | `max_steps`, `max_retries`, `max_generated_tools`, `max_execution_seconds` — the caps, copied from the lesson |
| `stop_reasons` | Appended markers such as `steps-budget-reached`; once present, the Governor denies further spend |
| `history` | Timestamped lifecycle events (`lesson_started`, `phase_skipped`, `lesson_closed`, …) |

Lifecycle is guarded too: `start_lesson` refuses `planned` lessons (they have
no budgets yet — scope is filled in when a version opens, never invented in
advance), and `close_lesson` refuses to close until every entry in the
lesson's `completion_criteria` is explicitly confirmed. `abort_lesson`
records its reason in `stop_reasons` rather than pretending completion.

## The per-concept phase machine

Each concept moves through four phases:

```
theory -> predicted -> observed -> explained
```

`evaluate` enforces the ordering when a `record` action is proposed:

- `predicted` may always be recorded;
- `observed` is denied unless the concept has reached `predicted`
  (rule `predict-before-observe`) — the student must commit to a prediction
  before seeing the packets;
- `explained` is denied unless the concept has reached `observed`
  (rule `observe-before-explain`) — explanations must be grounded in
  something actually seen.

The machine is **per concept, not per lesson**, and that choice comes from how
real lessons actually run. A lesson interleaves several concepts, and sessions
end mid-cycle: in `docs/lessons/v3.0-dns.md`, session 1 covered theory for all
seven DNS concepts, took the student's prediction about what the first `dig`
would put on the radio ("answered correctly; capture pending"), and closed for
the night — the live capture that turns that banked prediction into an
observation opens the next session. A single lesson-wide cycle could not
represent "this concept is at `predicted`, that one is still at `theory`";
`concept_phase` can, and it survives across sessions because it lives in
`state/lesson.json`.

The phase machine gates *pedagogy*; the learner model
(`packetlab/lab/learner.py`) separately gates *mastery* — a concept cannot
become `mastered` without at least one observation-or-transfer evidence entry
and one explanation entry.

## Scope: in_scope / out_of_scope

`curriculum/curriculum.json` gives every lesson explicit `in_scope` and
`out_of_scope` lists. When the agent proposes a `topic` action, the Governor
asks the curriculum:

- if the concept is in `in_scope`, it is allowed;
- if it is in `out_of_scope`, it is denied with rule `out-of-scope` and a
  reason that tells the agent what to do instead: *defer it to its own
  lesson*;
- anything else is denied as `unknown-concept`.

So during the DNS lesson (v3.0), `dns.udp-53` is allowed while `tcp`, `tls`,
`dnssec`, and `dns-over-https` are refused — even though TCP is a perfectly
good thing to teach, it belongs to v4.0. Tempting-but-off-goal is exactly the
drift the Governor exists to stop.

## Permitted command categories

Commands are grouped into categories defined in `packetlab/lab/policy.py`
(`COMMAND_CATEGORIES`): `observe_network`, `dns_query`, `ping`, `capture`,
`read_system_file`, `modify_neighbour_cache`. Each lesson grants a subset via
`permitted_categories`, and the curriculum loader rejects any lesson naming a
category the policy does not know.

Enforcement is two-layered:

1. the **Governor** checks that the category is granted to the active lesson
   and the step budget is not exhausted;
2. the **policy** (`check_command`) then checks the concrete argv against that
   category's allowlisted binaries, flag rules, path allowlists, and bounds.

A safe command in an ungranted category is still refused. The ARP lesson
(v2.0) grants `modify_neighbour_cache` because clearing a neighbour entry is
the experiment; the DNS lesson does not, so the same command is denied there.

## Budgets and stop reasons

Every non-planned lesson declares four caps:

| Budget | Counter it caps | Consumed by |
|---|---|---|
| `max_steps` | `steps` | each committed `run_command` or `invoke_tool` |
| `max_retries` | `retries` | commits whose outcome status is `nonzero`, `timeout`, `error`, or `output_cap` |
| `max_generated_tools` | `generated_tools` | each committed `generate_tool` |
| `max_execution_seconds` | `execution_seconds` | wall-clock duration reported in commit outcomes |

When a counter reaches its cap, `commit` appends a marker such as
`steps-budget-reached` to `stop_reasons` (once — markers are deduplicated),
and `evaluate` starts denying the corresponding action kinds
(`budget-steps`, `budget-tools`). The lesson does not silently grind on; the
state file says why it stopped.

## The two-phase protocol: evaluate (pure) / commit (mutator)

```python
decision = governor.evaluate(action)   # PURE: reads state, emits a trace
                                        # event, returns Decision, mutates nothing
# ... caller executes the action only if decision.allowed ...
governor.commit(action, outcome)        # the ONLY mutator: consumes budget,
                                        # advances phase, under the state lock
```

The split exists so budgets are **neither double-counted nor never-counted**:

- `evaluate` can be called any number of times — while planning, on retry
  after a denial, when re-checking after a resume — without spending anything.
  A *denied* action consumes no budget
  (`test_denied_action_consumes_no_budget`).
- `commit` is called exactly once, after the action actually ran, with the
  real outcome (duration, exit status). Nothing is spent for work that never
  happened, and nothing that happened goes unaccounted.
- All mutation goes through `statefile.update_json` — an flock-guarded,
  atomic, generation-checked read-modify-write — so two overlapping `lab`
  processes cannot drop each other's updates.

## The skip waiver

AGENTS.md's Pacing rules say that when the student says "go ahead", "move on",
or "just do it", the agent complies in that message without re-arguing. The
Governor honours this without corrupting the record: a `record` action with
`phase="skip"` is always allowed (rule `skip-waiver`), and on commit it
advances the concept one phase so the next step is unblocked, appending a
`phase_skipped` event to history. The learner model stores it as evidence of
kind `skip` — **never** as an observation or explanation — so a skipped gate
can unblock a lesson but can never manufacture mastery: `mastered` still
requires real observation and explanation evidence. The student controls
pacing; the record stays honest.

## Every decision is traced

Both halves of the protocol emit into the hash-chained JSONL trace
(`packetlab/lab/trace.py`): `evaluate` emits a `policy_decision` event
(action kind, category, concept, phase, `allowed`, `reason`, `rule`) and
`commit` emits `action_committed` with the outcome; lifecycle changes emit
`lesson_started` / `lesson_closed` / `lesson_aborted`. The test
`test_every_decision_is_traced_and_chain_verifies` runs decisions and then
verifies the chain end-to-end, and `docs/examples/trace-icmp-v1.1.jsonl` is a
real trace from a real lesson.

## Concrete example: allowed vs denied

With v3.0 (DNS) active — `permitted_categories` are `observe_network`,
`dns_query`, `ping`, `capture`, `read_system_file`:

```python
from packetlab.lab.governor import Action, Governor

gov.evaluate(Action("run_command", category="dns_query"))
# Decision(allowed=True,  rule="allow",
#          reason="'dns_query' within lesson scope and budget")

gov.evaluate(Action("run_command", category="modify_neighbour_cache"))
# Decision(allowed=False, rule="category-not-permitted",
#          reason="category 'modify_neighbour_cache' is not permitted for v3.0")

gov.evaluate(Action("topic", concept_id="tcp"))
# Decision(allowed=False, rule="out-of-scope",
#          reason="'tcp' is out of scope for v3.0; defer it to its own lesson")

gov.evaluate(Action("record", concept_id="dns.udp-53", phase="observed"))
# Decision(allowed=False, rule="predict-before-observe")  — no prediction yet
```

The same `ip neigh del` that the ARP lesson runs legitimately is refused in
the DNS lesson at the category layer, before the policy even looks at the
argv.

## Machine-authoritative curriculum, cross-checked

`curriculum/curriculum.json` is the structured twin of `ROADMAP.md` and is the
**machine-authoritative** source for scope, prerequisites, permitted
categories, and budgets; ROADMAP.md is the human-readable rendering. The
loader validates the graph on every load — concept ids must exist in the
top-level `concepts` map, permitted categories must be known to the policy,
prerequisites must reference real lessons, non-planned lessons must declare
budgets. `lab doctor` (`packetlab/lab/doctor.py`) cross-checks the two files:
every version's status must agree, and ROADMAP.md's headline progress
percentage must match the value computed from curriculum status, so a lesson
that is "complete" in one file and "planned" in the other cannot slip through.

## Verification

- `tests/test_governor.py` (part of the 96-test suite) covers the four
  properties directly: **Drift** (out-of-scope topics and ungranted categories
  denied, in-scope allowed), **Phases** (observe-before-predict denied, the
  full predicted→observed→explained walk, skip waiver satisfying a gate),
  **Budgets** (step and tool budgets stop further actions; denied actions
  spend nothing), **Lifecycle** (planned lessons cannot start, closing
  requires completion criteria, no-lesson denies everything, and every
  decision lands in a verifiable trace chain).
- The conformance evals (`python3 -m packetlab.lab eval`, 32 evals, all
  passing) exercise the Governor from outside the unit tests: the five
  `alignment` fixtures (out-of-scope refusal, in-scope allowance, ungranted
  category refusal, predict-before-observe, step-budget stop) and the four
  `teaching` fixtures (phase gates plus `teach-skip-waiver-honours-go-ahead`)
  all target `governor.evaluate` with expected decisions and rule ids.
