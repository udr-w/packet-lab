"""Fast, read-only lesson-resume snapshot.

One call answers "where is this learner and what happens next?" so a resume
costs a single CLI invocation instead of a doctor run plus seven document
reads. The snapshot is built ONLY from canonical learner state (the active
learner's files under state/learners/<id>/) plus the shared curriculum:

    canonical state, in priority order
      1. state/learners/<id>/lesson.json    (governor: lesson, phases, run)
      2. state/learners/<id>/learner.json   (mastery + evidence)
      3. curriculum/curriculum.json         (titles, concepts, next lesson)

Assistant chat memory is NEVER a source of lesson progress; it may only add
conversational colour. If chat memory and this snapshot disagree, the
snapshot wins.

Hard guarantees (tested in tests/test_resume.py):

- read-only: no file is created, modified, or deleted (no legacy migration,
  no run creation, no governor/learner mutation);
- no subprocesses, no network;
- reads only the ACTIVE learner's directory — never another learner's
  evidence, and never committed example traces under docs/;
- returns clearly when there is no active learner or nothing in progress.

The snapshot also carries a private-preflight recommendation (see
packetlab/lab/preflight.py) so the caller can decide whether any environment
validation is genuinely needed before the learner's next experiment.
"""

from __future__ import annotations

from pathlib import Path

from packetlab.lab import preflight as preflight_mod
from packetlab.lab.curriculum import Curriculum, Lesson
from packetlab.lab.curriculum import load as load_curriculum
from packetlab.lab.profiles import LearnerProfiles
from packetlab.lab.statefile import load_json
from packetlab.lab.trace import repo_root

SNAPSHOT_VERSION = 1

# Governor phases in teaching order; a concept is finished at "explained".
_PHASES = ("theory", "predicted", "observed", "explained")

# What the learner does next, given how far a concept has progressed.
_NEXT_ACTION = {
    "theory": "answer the warm-up prediction question",
    "predicted": "run the experiment and observe what actually happens",
    "observed": "explain the observation in their own words",
}

# Snapshot statuses the caller can rely on.
STATUS_RESUME = "resume"                    # unfinished lesson found
STATUS_FRESH = "fresh"                      # learner exists, no lesson yet
STATUS_NO_ACTIVE_LEARNER = "no_active_learner"
STATUS_ALL_COMPLETE = "all_complete"        # nothing left to resume or start


def build_snapshot(state_dir: Path | None = None,
                   curriculum: Curriculum | None = None) -> dict:
    """Build the resume snapshot. Read-only; see module docstring."""
    state_dir = state_dir or (repo_root() / "state")
    curriculum = curriculum or load_curriculum()

    profiles = LearnerProfiles(state_dir)
    # Deliberately no migrate_legacy_if_present(): migration writes files and
    # a resume snapshot must not.
    active = profiles.get_active()
    if active is None:
        return {
            "snapshot_version": SNAPSHOT_VERSION,
            "status": STATUS_NO_ACTIVE_LEARNER,
            "message": ("No active learner. Create one with "
                        "`learner create <id>` to begin."),
        }

    learner_dir = profiles.learner_dir(active)
    profile = load_json(learner_dir / "profile.json", default={})
    lesson_state = load_json(learner_dir / "lesson.json", default={})
    learner_model = load_json(learner_dir / "learner.json",
                              default={"concepts": {}})

    lesson, lesson_status = _resolve_lesson(curriculum, lesson_state)
    snapshot: dict = {
        "snapshot_version": SNAPSHOT_VERSION,
        "learner": {
            "id": active,
            "display_name": profile.get("display_name", active),
        },
    }

    if lesson is None:
        snapshot["status"] = STATUS_ALL_COMPLETE
        snapshot["message"] = ("Every startable lesson is complete; the next "
                               "curriculum version has not opened yet.")
        return snapshot

    phases = _concept_phases(lesson, lesson_state)
    unfinished = _first_unfinished(lesson, phases)
    evidence = _last_evidence(learner_model)
    open_prediction = _open_prediction(learner_model, phases)

    snapshot["status"] = STATUS_RESUME if lesson_status != "fresh" else STATUS_FRESH
    snapshot["lesson"] = {
        "id": lesson.lesson_id,
        "title": lesson.title,
        "status": lesson.status,
        "objective": lesson.objective,
        "run_open": lesson_status == "open_run",
    }
    snapshot["resume_note"] = _resume_note(lesson_state)
    snapshot["last_evidence"] = evidence
    snapshot["open_prediction"] = open_prediction
    snapshot["next"] = _next_step(curriculum, lesson, unfinished)
    snapshot["concept_progress"] = {
        "total": len(lesson.concepts),
        "finished": sum(1 for c in lesson.concepts
                        if phases.get(c) == "explained"),
    }
    snapshot["preflight"] = preflight_mod.plan(
        lesson, next_phase=(unfinished[1] if unfinished else None))
    # Operator-only details live under one key so renderers can drop it wholesale.
    snapshot["diagnostics"] = {
        "learner_state_source": str(learner_dir),
        "run_id": lesson_state.get("run_id"),
        "run_closed": bool(lesson_state.get("closed", True)),
        "run_aborted": bool(lesson_state.get("aborted", False)),
        "concept_phase": phases,
    }
    return snapshot


# ---- resolution helpers ----------------------------------------------------

def _resolve_lesson(curriculum: Curriculum,
                    lesson_state: dict) -> tuple[Lesson | None, str]:
    """Which lesson does this learner resume, and in what shape?

    Returns (lesson, status) where status is one of:
      open_run  — lesson.json has an unclosed run for it
      reopen    — last run closed/aborted but the lesson is not complete
      fresh     — no lesson history at all; first startable lesson
      (None, "none") — nothing to resume or start
    """
    lesson_id = lesson_state.get("lesson_id")
    if lesson_id:
        lesson = curriculum.lesson(lesson_id)
        if lesson is not None:
            if not lesson_state.get("closed"):
                return lesson, "open_run"
            if lesson.status != "complete":
                return lesson, "reopen"
    for lid in curriculum.order:
        lesson = curriculum.lesson(lid)
        if lesson.status != "complete" and lesson.budgets is not None:
            return lesson, ("fresh" if not lesson_id else "reopen")
    return None, "none"


def _concept_phases(lesson: Lesson, lesson_state: dict) -> dict:
    recorded = lesson_state.get("concept_phase", {}) \
        if lesson_state.get("lesson_id") == lesson.lesson_id else {}
    return {c: recorded.get(c, "theory") for c in lesson.concepts}


def _first_unfinished(lesson: Lesson, phases: dict) -> tuple[str, str] | None:
    """(concept_id, phase) of the first concept not yet explained."""
    for concept in lesson.concepts:
        phase = phases.get(concept, "theory")
        if phase != "explained":
            return concept, phase
    return None


def _resume_note(lesson_state: dict) -> str | None:
    reasons = lesson_state.get("stop_reasons") or []
    if reasons:
        return reasons[-1].get("reason")
    return None


def _last_evidence(learner_model: dict) -> dict | None:
    latest = None
    for concept_id, record in (learner_model.get("concepts") or {}).items():
        for entry in record.get("evidence", []):
            if latest is None or entry.get("ts", "") > latest["ts"]:
                latest = {"concept": concept_id, "ts": entry.get("ts", ""),
                          "kind": entry.get("kind", ""),
                          "summary": entry.get("summary", "")}
    return latest


def _open_prediction(learner_model: dict, phases: dict) -> dict | None:
    """A prediction awaiting its observation, if the governor says so."""
    for concept_id, phase in phases.items():
        if phase != "predicted":
            continue
        record = (learner_model.get("concepts") or {}).get(concept_id, {})
        predictions = [e for e in record.get("evidence", [])
                       if e.get("kind") == "prediction"]
        if predictions:
            return {"concept": concept_id,
                    "summary": predictions[-1].get("summary", "")}
        return {"concept": concept_id, "summary": ""}
    return None


def _next_step(curriculum: Curriculum, lesson: Lesson,
               unfinished: tuple[str, str] | None) -> dict:
    if unfinished is None:
        return {"kind": "close_lesson",
                "action": ("confirm the completion criteria and close "
                           f"{lesson.lesson_id}")}
    concept_id, phase = unfinished
    title = curriculum.concepts.get(concept_id, concept_id)
    return {"kind": "concept", "concept": concept_id, "concept_title": title,
            "phase": phase,
            "action": _NEXT_ACTION.get(phase, "continue the concept"),
            }


# ---- output renderers -------------------------------------------------------

# Operational vocabulary that must never reach the default learner view.
_OPERATOR_TERMS = ("run_id", "run-", "state/learners", "governor", "doctor",
                   "getcap", "trace", "preflight", "cap_net_raw", "diagnostic")


def render_learner(snapshot: dict) -> str:
    """The default view: welcome, lesson, where they stopped, one next step.

    No run IDs, paths, capability strings, or control-plane vocabulary.
    """
    status = snapshot.get("status")
    if status == STATUS_NO_ACTIVE_LEARNER:
        return ("No learner profile is selected yet.\n"
                "Ask your mentor to set one up, then try again.")
    if status == STATUS_ALL_COMPLETE:
        name = snapshot["learner"]["display_name"]
        return (f"Welcome back, {name}.\n"
                "Everything currently available is complete — the next "
                "lesson opens soon.")

    name = snapshot["learner"]["display_name"]
    lesson = snapshot["lesson"]
    lines = [f"Welcome back, {name}.", "",
             f"Lesson: {lesson['id']} — {lesson['title']}"]
    note = snapshot.get("resume_note")
    if status == STATUS_FRESH:
        lines.append("This is your first lesson — nothing to catch up on.")
    elif note:
        lines.append(f"Last time: {_learner_friendly_note(note)}")
    if snapshot.get("open_prediction") and snapshot["open_prediction"]["summary"]:
        pred = snapshot["open_prediction"]["summary"]
        lines.append(f"Your prediction is still on the table: {pred}")
    nxt = snapshot["next"]
    if nxt["kind"] == "concept":
        lines.append(f"Next: {nxt['concept_title']} — {nxt['action']}.")
    else:
        lines.append(f"Next: {nxt['action']}.")
    return "\n".join(lines)


def render_verbose(snapshot: dict) -> str:
    """Operator view: the learner view plus the machinery, clearly separated."""
    import json as _json
    parts = [render_learner(snapshot), "",
             "--- operator diagnostics (not for the learner) ---",
             _json.dumps({k: snapshot.get(k) for k in
                          ("status", "diagnostics", "preflight",
                           "concept_progress")},
                         indent=2, ensure_ascii=False, default=str)]
    return "\n".join(parts)


def _learner_friendly_note(note: str) -> str:
    """Strip operator phrasing from a stop reason before showing the learner."""
    friendly = note.split(". Resume")[0].strip()
    for term in ("no evidence recorded", "No evidence recorded"):
        friendly = friendly.replace(term, "").strip(" ;,.")
    return (friendly + ".") if friendly and not friendly.endswith(".") else friendly


# ---- schema -----------------------------------------------------------------

def validate_snapshot(snapshot: dict) -> list[str]:
    """Check a snapshot against its declared shape. Returns problems ([] = ok)."""
    problems: list[str] = []
    if snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        problems.append("snapshot_version missing or wrong")
    status = snapshot.get("status")
    if status not in (STATUS_RESUME, STATUS_FRESH, STATUS_NO_ACTIVE_LEARNER,
                      STATUS_ALL_COMPLETE):
        problems.append(f"unknown status {status!r}")
        return problems
    if status == STATUS_NO_ACTIVE_LEARNER:
        if not isinstance(snapshot.get("message"), str):
            problems.append("no_active_learner snapshot needs a message")
        return problems
    learner = snapshot.get("learner")
    if not (isinstance(learner, dict) and isinstance(learner.get("id"), str)):
        problems.append("learner.id missing")
    if status == STATUS_ALL_COMPLETE:
        return problems
    lesson = snapshot.get("lesson")
    if not (isinstance(lesson, dict) and isinstance(lesson.get("id"), str)
            and isinstance(lesson.get("title"), str)):
        problems.append("lesson.id/title missing")
    nxt = snapshot.get("next")
    if not (isinstance(nxt, dict) and isinstance(nxt.get("action"), str)):
        problems.append("next.action missing")
    pf = snapshot.get("preflight")
    if not (isinstance(pf, dict) and "recommended" in pf
            and isinstance(pf.get("checks"), list)):
        problems.append("preflight block missing or malformed")
    diag = snapshot.get("diagnostics")
    if not isinstance(diag, dict):
        problems.append("diagnostics block missing")
    return problems
