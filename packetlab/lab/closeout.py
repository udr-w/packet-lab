"""Session close-out: repository mutation proportional to durable value.

The failure this replaces: a learner resumed, answered nothing, had to
leave — and the close appended a session section to the lesson narrative,
rewrote TASK.md and docs/handover.md, committed, rebased, and pushed. Forty
lines across three documents, a commit, and a two-minute wait, all saying
"nothing happened" — while the canonical resume point already lived in the
learner's own lesson.json. Documentation write amplification: the same
non-event stored in seven places.

The rule here: a fact has ONE authoritative home.

    learner position/evidence   state/learners/<id>/ (private, gitignored)
    interruption reason         lesson.json stop_reasons (state, not docs)
    what happened mechanically  the run trace (already recorded, hash-chained)
    the milestone plan          TASK.md — changes when the PLAN changes
    the learning story          docs/lessons/ — learning content only, never
                                administrative events
    durable concepts            docs/knowledge/
    durable status + profile    docs/handover.md — milestones and standing
                                directives, not sessions
    Git history                 durable shared value, never a session log

`classify()` reads the run trace and says what kind of session this was;
`persistence_policy()` says what may be written as a result. A no-op close
touches learner state only: the aborted run IS the minimum durable record,
and the next resume derives everything from it.
"""

from __future__ import annotations

# Record phases that constitute learning evidence. A skip is a waiver, not
# evidence: a session of nothing but skips still closes as no_op.
EVIDENCE_PHASES = ("predicted", "observed", "explained")

CLASS_NO_OP = "no_op"           # no evidence, no artifact (incl. talk-only)
CLASS_EVIDENCE = "evidence"     # learning evidence was recorded
CLASS_MILESTONE = "milestone"   # lesson closed via completion criteria


def classify(events: list[dict], changed_repo_files: tuple = ()) -> dict:
    """Deterministic session classification from the run trace.

    `changed_repo_files` is `git status --porcelain` paths; anything outside
    state/ means engineering work happened alongside the lesson and must be
    delivered under repository-owner mode (it never changes the learner-facing
    close, which stays fast).
    """
    evidence = 0
    skips = 0
    commands = 0
    closed = False
    for event in events:
        if event.get("event") == "action_committed" \
                and event.get("kind") == "record":
            if event.get("phase") in EVIDENCE_PHASES:
                evidence += 1
            elif event.get("phase") == "skip":
                skips += 1
        elif event.get("event") == "command_executed":
            commands += 1
        elif event.get("event") == "lesson_closed":
            closed = True

    if closed:
        session_class = CLASS_MILESTONE
    elif evidence:
        session_class = CLASS_EVIDENCE
    else:
        session_class = CLASS_NO_OP

    engineering = [f for f in changed_repo_files
                   if f and not f.startswith("state/")]
    return {"class": session_class, "evidence_events": evidence,
            "skips": skips, "commands": commands,
            "engineering_changes": engineering}


def persistence_policy(classification: dict) -> dict:
    """What this session has EARNED the right to write.

    Everything not listed true stays untouched. Notes are constraints that
    apply whenever a document is written at all.
    """
    session_class = classification["class"]
    policy = {
        CLASS_NO_OP: {
            "lesson_narrative": False, "task_md": False, "handover": False,
            "knowledge": False, "roadmap": False, "commit": False,
            "push": False,
        },
        CLASS_EVIDENCE: {
            "lesson_narrative": True,
            "task_md": "only if the milestone plan itself changed",
            "handover": False,
            "knowledge": "only if durable understanding emerged",
            "roadmap": False,
            "commit": True, "push": False,
        },
        CLASS_MILESTONE: {
            "lesson_narrative": True, "task_md": True, "handover": True,
            "knowledge": True, "roadmap": True, "commit": True, "push": True,
        },
    }[session_class]
    result = dict(policy)
    result["notes"] = [
        "docs record learning, not administration — never write that a "
        "session opened, ended early, or was aborted; the run state already "
        "holds that",
        "never copy learner-private evidence verbatim into shared docs; "
        "summarize the learning and cite the run id",
        "one authoritative home per fact: reference, don't duplicate",
    ]
    if classification.get("engineering_changes"):
        result["engineering"] = (
            "repo files changed outside state/ — deliver them under "
            "repository-owner mode (doctor, tests, commit, push) after the "
            "learner has been released")
    return result


def learner_farewell(classification: dict) -> str:
    """One warm, jargon-free sentence to close with. No recap, no ceremony."""
    session_class = classification["class"]
    if session_class == CLASS_NO_OP:
        return ("No problem — lesson paused, nothing lost. Next time you'll "
                "pick up exactly where we stopped.")
    if session_class == CLASS_EVIDENCE:
        return ("Good session — your progress is saved. Next time we "
                "continue from exactly here.")
    return "Milestone closed — great work. See you in the next lesson."
