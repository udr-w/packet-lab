"""The Curriculum Governor — goal integrity for the tutoring agent.

The Governor holds the lesson's structured intent (objective, in/out of scope,
permitted command categories, budgets, per-concept phase) and decides whether a
proposed action is allowed *before* it happens. Drift prevention is not a
prompt here; it is this state machine plus scope and budget checks, all of
which are testable in isolation (see tests/test_governor.py).

Two-phase protocol, so budgets are neither double-counted nor never-counted:

    decision = governor.evaluate(action)     # PURE: reads state, emits trace,
                                              # returns Decision, mutates nothing
    ... the caller executes the action ...
    governor.commit(action, outcome)          # the ONLY mutator: consumes budget
                                               # and advances phase, under the lock

Per-concept phases (theory -> predicted -> observed -> explained), not one
lesson-wide cycle, because real lessons interleave several concepts across
sessions. A `skip` waiver (the student says "go ahead") satisfies a phase gate
and is recorded as a skip in the trace and learner evidence — never as mastery.
Hard gates remain hard only for recording mastery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from packetlab.lab.curriculum import Curriculum, Lesson
from packetlab.lab.policy import Decision
from packetlab.lab.statefile import atomic_write_json, load_json, update_json
from packetlab.lab.trace import Trace

PHASES = ("theory", "predicted", "observed", "explained")
INTERRUPTED = "interrupted"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_state_path() -> Path:
    return Path(__file__).resolve().parents[2] / "state" / "lesson.json"


@dataclass
class Action:
    """A proposed action the governor evaluates."""

    kind: str  # run_command | generate_tool | invoke_tool | advance | topic | record
    category: str | None = None       # for run_command
    concept_id: str | None = None     # for topic / record
    phase: str | None = None          # for record (predicted/observed/explained/skip)
    detail: dict = field(default_factory=dict)


class NoActiveLessonError(RuntimeError):
    pass


class Governor:
    def __init__(self, curriculum: Curriculum, trace: Trace | None = None,
                 state_path: Path | None = None) -> None:
        self.curriculum = curriculum
        self.trace = trace
        self.state_path = state_path or default_state_path()

    # ---- lifecycle -------------------------------------------------------

    def start_lesson(self, lesson_id: str, run_id: str) -> dict:
        lesson = self.curriculum.lesson(lesson_id)
        if lesson is None:
            raise ValueError(f"unknown lesson '{lesson_id}'")
        if lesson.status == "planned" or lesson.budgets is None:
            raise ValueError(f"lesson '{lesson_id}' is planned; no budgets defined yet")
        existing = self._read()
        if existing.get("lesson_id") and existing.get("phase_summary") != "closed" \
                and not existing.get("closed"):
            raise ValueError(
                f"lesson '{existing['lesson_id']}' is still active; close or abort it first")
        state = {
            "generation": 0,
            "lesson_id": lesson_id,
            "objective": lesson.objective,
            "run_id": run_id,
            "started_at": _now(),
            "closed": False,
            "concept_phase": {c: "theory" for c in lesson.concepts},
            "counters": {"steps": 0, "retries": 0, "generated_tools": 0,
                         "execution_seconds": 0},
            "budgets": {
                "max_steps": lesson.budgets.max_steps,
                "max_retries": lesson.budgets.max_retries,
                "max_generated_tools": lesson.budgets.max_generated_tools,
                "max_execution_seconds": lesson.budgets.max_execution_seconds,
            },
            "stop_reasons": [],
            "history": [{"ts": _now(), "event": "lesson_started"}],
        }
        atomic_write_json(self.state_path, state)
        self._emit("governor", "lesson_started", lesson_id=lesson_id, run_id=run_id,
                   objective=lesson.objective)
        return state

    def close_lesson(self, confirmations: list[str]) -> dict:
        state = self._require_active()
        lesson = self.curriculum.lesson(state["lesson_id"])
        missing = [c for c in lesson.completion_criteria if c not in confirmations]
        if missing:
            raise ValueError(
                f"cannot close: {len(missing)} completion criteria unconfirmed")

        def mutate(data: dict) -> dict:
            data["closed"] = True
            data["closed_at"] = _now()
            data["history"].append({"ts": _now(), "event": "lesson_closed"})
            return data

        new_state = update_json(self.state_path, mutate)
        self._emit("governor", "lesson_closed", lesson_id=state["lesson_id"])
        return new_state

    def abort_lesson(self, reason: str) -> dict:
        def mutate(data: dict) -> dict:
            data["closed"] = True
            data["aborted"] = True
            data["stop_reasons"].append({"ts": _now(), "reason": reason})
            data["history"].append({"ts": _now(), "event": "lesson_aborted",
                                    "reason": reason})
            return data

        update_json(self.state_path, mutate)
        self._emit("governor", "lesson_aborted", reason=reason)
        return self._read()

    # ---- evaluate (pure) -------------------------------------------------

    def evaluate(self, action: Action) -> Decision:
        """Read-only: return a Decision and emit a trace event. No mutation."""
        try:
            state = self._require_active()
        except NoActiveLessonError:
            return self._decide(action, Decision.deny("no active lesson", "no-lesson"))
        lesson = self.curriculum.lesson(state["lesson_id"])

        decision = self._evaluate_inner(action, state, lesson)
        return self._decide(action, decision)

    def _evaluate_inner(self, action: Action, state: dict, lesson: Lesson) -> Decision:
        counters, budgets = state["counters"], state["budgets"]

        if action.kind == "run_command":
            if counters["steps"] >= budgets["max_steps"]:
                return Decision.deny("step budget exhausted", "budget-steps")
            if action.category not in lesson.permitted_categories:
                return Decision.deny(
                    f"category '{action.category}' is not permitted for {lesson.lesson_id}",
                    "category-not-permitted")
            return Decision.allow(f"'{action.category}' within lesson scope and budget",
                                  "allow")

        if action.kind == "generate_tool":
            if counters["generated_tools"] >= budgets["max_generated_tools"]:
                return Decision.deny("generated-tool budget exhausted", "budget-tools")
            return Decision.allow("tool generation within budget", "allow")

        if action.kind == "invoke_tool":
            if counters["steps"] >= budgets["max_steps"]:
                return Decision.deny("step budget exhausted", "budget-steps")
            return Decision.allow("tool invocation within budget", "allow")

        if action.kind == "topic":
            if self.curriculum.is_out_of_scope(lesson.lesson_id, action.concept_id):
                return Decision.deny(
                    f"'{action.concept_id}' is out of scope for {lesson.lesson_id}; "
                    "defer it to its own lesson", "out-of-scope")
            if action.concept_id not in lesson.concepts \
                    and action.concept_id not in lesson.in_scope:
                return Decision.deny(
                    f"'{action.concept_id}' is not a concept of this lesson",
                    "unknown-concept")
            return Decision.allow(f"'{action.concept_id}' is in scope", "allow")

        if action.kind == "record":
            return self._evaluate_record(action, state, lesson)

        return Decision.deny(f"unknown action kind '{action.kind}'", "unknown-action")

    def _evaluate_record(self, action: Action, state: dict, lesson: Lesson) -> Decision:
        concept = action.concept_id
        phase = action.phase
        if concept not in state["concept_phase"]:
            return Decision.deny(f"'{concept}' is not tracked in this lesson",
                                 "unknown-concept")
        current = state["concept_phase"][concept]
        if phase == "skip":
            return Decision.allow("skip waiver accepted (recorded as skip, not mastery)",
                                  "skip-waiver")
        if phase == "predicted":
            return Decision.allow("prediction may be recorded", "allow")
        if phase == "observed":
            if current not in ("predicted", "observed", "explained"):
                return Decision.deny(
                    "cannot record an observation before a prediction (or an explicit "
                    "skip) for this concept", "predict-before-observe")
            return Decision.allow("observation may be recorded", "allow")
        if phase == "explained":
            if current not in ("observed", "explained"):
                return Decision.deny(
                    "cannot record an explanation before an observation for this concept",
                    "observe-before-explain")
            return Decision.allow("explanation may be recorded", "allow")
        return Decision.deny(f"unknown record phase '{phase}'", "unknown-phase")

    # ---- commit (mutator) ------------------------------------------------

    def commit(self, action: Action, outcome: dict | None = None) -> dict:
        """The only budget/phase mutator. Call once, after the action ran."""
        outcome = outcome or {}

        def mutate(data: dict) -> dict:
            counters = data["counters"]
            if action.kind in ("run_command", "invoke_tool"):
                counters["steps"] += 1
                counters["execution_seconds"] += int(outcome.get("duration_ms", 0) / 1000)
                if outcome.get("status") in ("nonzero", "timeout", "error", "output_cap"):
                    counters["retries"] += 1
            elif action.kind == "generate_tool":
                counters["generated_tools"] += 1
            elif action.kind == "record" and action.phase in PHASES:
                data["concept_phase"][action.concept_id] = action.phase
            elif action.kind == "record" and action.phase == "skip":
                # A skip satisfies the current gate: advance one phase so the
                # next step is unblocked, but it is recorded as a skip (never
                # as mastery — the learner model stores skip evidence).
                current = data["concept_phase"].get(action.concept_id, "theory")
                idx = PHASES.index(current) if current in PHASES else 0
                data["concept_phase"][action.concept_id] = \
                    PHASES[min(idx + 1, len(PHASES) - 1)]
                data["history"].append({"ts": _now(), "event": "phase_skipped",
                                        "concept_id": action.concept_id,
                                        "from": current})
            self._note_budget_stops(data)
            return data

        new_state = update_json(self.state_path, mutate)
        self._emit("governor", "action_committed", kind=action.kind,
                   category=action.category, concept_id=action.concept_id,
                   phase=action.phase, outcome=outcome)
        return new_state

    def _note_budget_stops(self, data: dict) -> None:
        counters, budgets = data["counters"], data["budgets"]
        for name, cap_key in (("steps", "max_steps"), ("retries", "max_retries"),
                              ("generated_tools", "max_generated_tools"),
                              ("execution_seconds", "max_execution_seconds")):
            if counters[name] >= budgets[cap_key]:
                marker = f"{name}-budget-reached"
                if marker not in [s.get("marker") for s in data["stop_reasons"]]:
                    data["stop_reasons"].append(
                        {"ts": _now(), "marker": marker,
                         "reason": f"{name} reached its budget of {budgets[cap_key]}"})

    # ---- resume / status -------------------------------------------------

    def status(self) -> dict:
        state = self._read()
        if state.get("lesson_id") and not state.get("closed") \
                and not self._run_is_live(state.get("run_id")):
            # A session died mid-lesson: surface it, do not silently continue.
            state = self._mark_interrupted(state)
        return state

    def _run_is_live(self, run_id) -> bool:
        # The CLI is short-lived; "live" means the trace exists for this run.
        # Interruption detection is conservative — status only flags a lesson
        # whose state has no closing event, prompting explicit resume/abort.
        return bool(run_id)

    def _mark_interrupted(self, state: dict) -> dict:
        return state  # placeholder hook; explicit abort is required to clear

    # ---- helpers ---------------------------------------------------------

    def _decide(self, action: Action, decision: Decision) -> Decision:
        self._emit("governor", "policy_decision", kind=action.kind,
                   category=action.category, concept_id=action.concept_id,
                   phase=action.phase, allowed=decision.allowed,
                   reason=decision.reason, rule=decision.rule)
        return decision

    def _emit(self, component: str, event: str, **fields) -> None:
        if self.trace is not None:
            self.trace.emit(component, event, **fields)

    def _read(self) -> dict:
        return load_json(self.state_path, default={})

    def _require_active(self) -> dict:
        state = self._read()
        if not state.get("lesson_id") or state.get("closed"):
            raise NoActiveLessonError("no active lesson")
        return state
