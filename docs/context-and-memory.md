# Context and memory

Packet Lab's agent is stateless between sessions; the repository is its memory.
This is deliberate: structured files a reviewer can read beat a growing chat log
the reviewer cannot. This document describes what context each role assembles,
what it must not see, and how external text is kept from becoming instructions.

## The repository is the memory

`AGENTS.md` makes it a standing rule: the repository is the source of truth, not
prior chat history. When something durable is learned, the agent updates a file,
not its own memory of the conversation. The memory is therefore inspectable,
diff-able, and size-capped:

| Store | Role | Lifecycle |
|---|---|---|
| `curriculum/curriculum.json` | curriculum graph, scope, budgets | shared; machine-authoritative |
| `state/learners/<id>/lesson.json` | that learner's current lesson, phase, budgets, counters | per learner; rewritten each session |
| `state/learners/<id>/learner.json` | that learner's per-concept mastery + evidence | per learner; append evidence, state derived |
| `state/learners/<id>/tools/…/provenance.json` | that learner's generated tools + provenance | per learner; retention-scoped |
| `state/learners/<id>/runs/<run>/trace.jsonl` | hash-chained run events (labelled with learner id) | per learner; append-only per run |
| `state/active-learner` | which learner is currently selected | pointer |
| `tools/registry.json` | shared/built-in tool registry scaffold | shared |
| `TASK.md`, `docs/handover.md` | current milestone / resume pointer | rewritten fresh, size-capped |
| `docs/lessons/*.md` | session narrative | append-only within a milestone |
| `docs/knowledge/*.md` | distilled, deduplicated concepts | cold reference |

`scripts/lab-doctor.py` enforces the size caps so the narrative history never
grows without bound, and `lab doctor` additionally cross-checks that the machine
state (`curriculum.json`) and the human view (`ROADMAP.md`) agree.

## What each role sees (and does not)

Context is assembled per role from the structured stores, not by dumping the
whole repository or conversation into every prompt.

| Role | Should see | Should not see |
|---|---|---|
| Tutor | current objective + phase, relevant learner state, recent observations | tool source, full trace history, unrelated lessons |
| Experiment Designer | objective, permitted categories, available tool catalogue, relevant failures | learner's private evidence beyond the current concept |
| Tool Engineer | the capability gap, the tool spec contract, the registry (for reuse) | the learner model, unrelated lesson state |
| Explanation judgement | the learner's answer, the concept definition, the expected observation | the answer key phrased as an instruction to accept |

Because the stores are structured, "the relevant learner state" is a concrete
query (`learner.concept(id)`), not a guess, and stale narrative is discarded by
the rewrite-fresh discipline rather than accumulating.

## Untrusted text is data, never instructions

Command output, file contents, packet payloads, and generated-tool comments are
attacker-influenceable. Whenever any of it is surfaced to the agent, it goes
through `untrusted.render` (`packetlab/lab/untrusted.py`):

- wrapped in explicit `<<UNTRUSTED-DATA …>> … <<END-UNTRUSTED-DATA>>` markers so
  embedded text reads as quoted data;
- stripped of ANSI escapes and C0 control characters so captured output cannot
  move the cursor or smuggle terminal sequences;
- defanged if the payload forges the closing marker (rewritten to
  `redacted-marker`), so it cannot break out of the block;
- flagged with best-effort injection heuristics (`looks_like_injection`) for the
  trace, which is detection for review, not a defence.

The honest point, stated in the threat model: wrapping does not force a model to
obey it. The real containment is downstream — even a hijacked agent still acts
through the command policy, the Governor's scope/budget gates, and the restricted
runner, so injection can corrupt the *tutoring* but not the *host* along the
guarded path. The `injection` eval category asserts that wrapping and defanging
are applied at every output surface; it does not (and cannot) assert model
resistance, and `docs/evaluation-strategy.md` says so.

## Per-learner context isolation

Packet Lab is multi-learner, so "the relevant learner state" is always **the
active learner's** state and nothing else. All live learner state is namespaced
under `state/learners/<id>/` (profile, governor state, mastery model, traces,
workspace, tools). When the assistant starts or resumes a lesson, its context
must contain only the selected learner's mastery, that learner's recent
evidence, the current lesson, and shared curriculum/policy — never another
learner's predictions, explanations, misconceptions, mastery, history, or
identity. Committed example evidence (labelled `learner-example`) is historical
demonstration data and is never loaded into a live learner's active context.
The active learner appears in every command's output and every trace event, so
the correct profile is always visible. This is enforced structurally (separate
files per learner) and checked by `tests/test_profiles.py` and the
`personalization` evals; the rule is also stated in `AGENTS.md`.

## Contradictions and staleness

- **Contradiction:** if a later observation contradicts a recorded belief, the
  concept can be marked `needs_review`, and the derived state falls back until a
  fresh observation-plus-explanation supersedes it.
- **Staleness:** machine facts (IP addresses, MACs, DNS servers) are always
  re-derived live from the system, never trusted from an old note — the lesson
  docs record them as *observed values*, not constants.
- **Reset/export:** `learner reset` clears the model; the learner state file is
  plain JSON, so exporting it is reading the file. What is persisted is limited
  to concept evidence summaries and lesson/run ids — no broader personal data.
