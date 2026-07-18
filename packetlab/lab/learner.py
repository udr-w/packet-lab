"""Concept-level learner model.

Mastery is tracked per concept, not per lesson, and every state change is
backed by an evidence entry that cites the lesson and run it came from. The
evidence is the credibility mechanism: a reviewer can diff each summary against
the committed narrative in docs/lessons/*.md.

Mastery is *asserted by the tutoring agent*, not graded by an independent
model. That is an honest limitation (see docs/learning-model.md); the evidence
trail is what makes the assertion auditable. A separate-model evaluator is a
roadmap item, not a current capability.

States are deliberately few — the richness lives in the evidence list, not in a
long ladder of states that would fight the one-question-per-concept pacing:

    unseen -> in_progress -> mastered   (needs_review reachable from anywhere)

`mastered` requires at least one observation-or-transfer evidence entry AND at
least one explanation entry for that concept, so mastery cannot be claimed from
theory alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from packetlab.lab.statefile import atomic_write_json, load_json, update_json

STATES = ("unseen", "in_progress", "needs_review", "mastered")
EVIDENCE_KINDS = ("introduction", "prediction", "observation", "explanation",
                  "transfer", "skip", "evaluator_note")
MAX_EVIDENCE_SUMMARY = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "state" / "learner.json"


@dataclass(frozen=True)
class ConceptState:
    concept_id: str
    state: str
    evidence: tuple
    updated_at: str


class LearnerModel:
    """A thin, validated wrapper over state/learner.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()

    def load(self) -> dict:
        return load_json(self.path, default={"version": 1, "concepts": {}})

    def concept(self, concept_id: str) -> ConceptState:
        data = self.load()
        entry = data["concepts"].get(concept_id)
        if entry is None:
            return ConceptState(concept_id, "unseen", (), "")
        return ConceptState(concept_id, entry["state"], tuple(entry["evidence"]),
                            entry.get("updated_at", ""))

    def add_evidence(self, concept_id: str, kind: str, summary: str,
                     lesson_id: str, run_id: str | None) -> ConceptState:
        """Record evidence and recompute the concept's state deterministically."""
        if kind not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence kind '{kind}'")
        summary = summary[:MAX_EVIDENCE_SUMMARY]
        entry = {"ts": _now(), "kind": kind, "summary": summary,
                 "lesson_id": lesson_id, "run_id": run_id}

        def mutate(data: dict) -> dict:
            concepts = data.setdefault("concepts", {})
            record = concepts.setdefault(
                concept_id, {"state": "unseen", "evidence": [], "updated_at": ""})
            record["evidence"].append(entry)
            record["state"] = _derive_state(record["evidence"])
            record["updated_at"] = entry["ts"]
            return data

        data = update_json(self.path, mutate,
                           default={"version": 1, "concepts": {}, "generation": 0})
        record = data["concepts"][concept_id]
        return ConceptState(concept_id, record["state"], tuple(record["evidence"]),
                            record["updated_at"])

    def mark_needs_review(self, concept_id: str, reason: str, lesson_id: str,
                          run_id: str | None) -> ConceptState:
        return self.add_evidence(concept_id, "evaluator_note",
                                 f"needs review: {reason}", lesson_id, run_id)

    def summary(self) -> dict:
        data = self.load()
        counts = {state: 0 for state in STATES}
        for entry in data["concepts"].values():
            counts[entry["state"]] = counts.get(entry["state"], 0) + 1
        return {"total_concepts": len(data["concepts"]), "by_state": counts}

    def reset(self) -> None:
        atomic_write_json(self.path, {"version": 1, "concepts": {}, "generation": 0})


def _derive_state(evidence: list[dict]) -> str:
    """Pure function: concept state follows only from its evidence."""
    kinds = {e["kind"] for e in evidence}
    last_note = next((e for e in reversed(evidence)
                      if e["kind"] == "evaluator_note"
                      and e["summary"].startswith("needs review")), None)
    if last_note is not None:
        # needs_review persists until a later observation/explanation supersedes it.
        later = [e for e in evidence if e["ts"] >= last_note["ts"]
                 and e["kind"] in ("observation", "explanation", "transfer")]
        if not later:
            return "needs_review"
    has_grounding = bool(kinds & {"observation", "transfer"})
    has_explanation = "explanation" in kinds
    if has_grounding and has_explanation:
        return "mastered"
    # Real evidence beyond skips means progress; a concept whose only evidence
    # is skips does not read as progress (it was waved past, not learned).
    return "in_progress" if (kinds - {"skip"}) else "unseen"
