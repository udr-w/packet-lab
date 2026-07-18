---
name: resume-lesson
description: Resume the active Packet Lab lesson fast. Use for "resume lesson", "continue lesson", "where did we stop", "continue Packet Lab", "start from where I left off", or any request to pick the current lesson back up.
---

# Fast Resume Protocol

This is the ONE protocol for resuming a lesson, whether the learner typed
`/resume-lesson` or said it in natural language. Target: first visible
acknowledgement within ~5 seconds, lesson-ready response shortly after. The
learner must never face silent multi-minute startup.

## Steps

1. **Acknowledge first.** Before any tool call, send one short learner-facing
   sentence, e.g. "Welcome back — loading your lesson and checking the next
   experiment." No fabricated progress percentages; meaningful phases only
   ("Finding your unfinished lesson", "Checking the next experiment"), and
   normally at most one or two such messages.
2. **One snapshot call.** Run `./packet-lab.sh resume --json` exactly once.
   It is read-only and canonical: active learner, current lesson, where they
   stopped, any open prediction, the one next action, and a preflight
   recommendation. Trust it — do not re-derive state from docs, chat memory,
   doctor runs, tests, or other learners' files.
3. **Decide on private preflight.** Only if `preflight.recommended` is true.
   Run `./packet-lab.sh preflight --json` for capability checks. Run a live
   representative probe ONLY when the plan's outcome is `lightweight` AND the
   learner's prediction for the affected concept is already recorded —
   otherwise defer it until immediately before the learner's experiment.
4. **Keep preflight private and clean.** Use the plan's
   `disposable_hostname`; never query or touch a target the learner will
   use; obey every listed contamination control. Never show preflight
   output, run IDs, capability strings, or packet dumps to the learner.
   Preflight is never learner evidence and never advances mastery or phase.
5. **Respond concisely.** Brief welcome → current lesson → one sentence on
   where they stopped (restate any open prediction) → ONE focused,
   goal-oriented question or action. Do not dump the roadmap, upcoming
   steps, or health reports.
6. **Preserve the learning loop.** The learner predicts before they observe;
   your private verification never substitutes for their experiment or
   reveals its expected result.
7. **Lazy-load detail.** Open TASK.md or the current docs/lessons file only
   when the identified next step needs its detail (e.g. exact experiment
   wording) — not as part of resuming.
8. **On failure, be honest and plain.** If the snapshot reports a blocker or
   preflight fails, use the provided learner-facing message: what it means
   for today's lesson, no implementation jargon. If validation contradicts
   the lesson's assumptions, say so — never invent expected results.

## Never at resume time

- lab-doctor / doctor / tests / evals / demo
- reading README, ROADMAP, architecture docs, or every lesson file
- starting a lesson run or mutating any learner state
- raw tcpdump / dig / ping / getcap outside the preflight plan
- another learner's state, or committed examples under docs/examples/
