---
name: end-lesson
description: End or pause the current Packet Lab session. Use for "end lesson", "end lesson for today", "I have to go", "let's stop here", "pause the lesson", "stop for today", or any request to wrap up or leave the session.
---

# Proportional Session Close

Closing a lesson feels like closing a notebook, not a release ceremony. The
learner is released first; any earned repository work happens after.

## Steps

1. **One command.** Run
   `./packet-lab.sh lesson end --reason "<one line>"`
   (alias: `./packet-lab.sh close --reason "..."`). It aborts any open run —
   the reason lands in learner state, the canonical resume point — and
   prints the session class and persistence policy.
2. **Release the learner immediately.** Reply with the printed
   `learner_message` (or your own one-or-two warm sentences). No recap, no
   diagnostics, no operational narration, no progress ceremony.
3. **Then follow the printed policy exactly:**
   - `no_op` — nothing else. No doc edits, no commit, no push. The aborted
     run is the complete durable record; the next resume derives the exact
     question from canonical state.
   - `evidence` — after the farewell: append the session's LEARNING content
     to the current docs/lessons file (never administrative events), update
     docs/knowledge only if durable understanding emerged, TASK.md only if
     the plan changed. Commit locally; do NOT push.
   - `milestone` — the full wrap-up per AGENTS.md "end lesson for today",
     including push and the ROADMAP progress line.
   - `engineering` flag — deliver code/doc changes under repository-owner
     mode (doctor, tests, commit, push) after the learner is gone.

## Never at close time

- doctor/tests/evals for a no_op or evidence session (milestone/engineering
  only)
- writing that a session "opened and ended early" anywhere
- copying learner-private evidence into shared docs
- making the learner wait for commits, pushes, rebases, or CI
