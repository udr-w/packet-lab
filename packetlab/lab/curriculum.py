"""Curriculum graph loader and validator.

curriculum/curriculum.json is the structured twin of ROADMAP.md. It is the
machine-authoritative source for lesson scope, prerequisites, permitted
command categories, and budgets; ROADMAP.md is a human-readable rendering.
`lab doctor` cross-checks the two and fails on divergence, so a lesson that is
'complete' in one and 'planned' in the other cannot slip through.

Concept ids referenced anywhere (lessons, experiment specs, the learner model)
must exist in the top-level `concepts` map — the loader rejects dangling refs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from packetlab.lab.policy import known_categories


@dataclass(frozen=True)
class Budgets:
    max_steps: int
    max_retries: int
    max_generated_tools: int
    max_execution_seconds: int

    @staticmethod
    def from_dict(data: dict) -> "Budgets":
        return Budgets(
            max_steps=int(data["max_steps"]),
            max_retries=int(data["max_retries"]),
            max_generated_tools=int(data["max_generated_tools"]),
            max_execution_seconds=int(data["max_execution_seconds"]),
        )


@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    title: str
    status: str  # complete | in_progress | planned
    objective: str
    concepts: tuple
    prerequisites: tuple
    in_scope: tuple
    out_of_scope: tuple
    permitted_categories: tuple
    budgets: Budgets | None
    completion_criteria: tuple


@dataclass(frozen=True)
class Curriculum:
    concepts: dict
    lessons: dict  # lesson_id -> Lesson
    order: tuple  # lesson_ids in file order

    def lesson(self, lesson_id: str) -> Lesson | None:
        return self.lessons.get(lesson_id)

    def is_out_of_scope(self, lesson_id: str, concept_id: str) -> bool:
        lesson = self.lessons.get(lesson_id)
        if lesson is None:
            return True
        if concept_id in lesson.in_scope:
            return False
        return concept_id in lesson.out_of_scope

    def progress(self) -> tuple[int, int, int]:
        """Return (complete, total_versions, percent). Counts closed versions."""
        versions = [lid for lid in self.order if lid.endswith(".0") or lid == "v1.0"]
        # Versions are grouped by the leading integer; a version counts complete
        # when every lesson under it is complete.
        by_version: dict[str, list[Lesson]] = {}
        for lesson in self.lessons.values():
            major = lesson.lesson_id.split(".")[0]  # 'v3'
            by_version.setdefault(major, []).append(lesson)
        total = len(by_version)
        complete = sum(1 for lessons in by_version.values()
                       if all(le.status == "complete" for le in lessons))
        del versions
        percent = round(100 * complete / total) if total else 0
        return complete, total, percent


def default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "curriculum" / "curriculum.json"


def load(path: Path | None = None) -> Curriculum:
    path = path or default_path()
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    concepts = data.get("concepts", {})
    if not isinstance(concepts, dict):
        raise ValueError("curriculum.concepts must be an object")

    categories = set(known_categories())
    lessons: dict = {}
    order: list[str] = []
    seen_ids: set = set()

    for raw in data["lessons"]:
        lesson_id = raw["lesson_id"]
        if lesson_id in seen_ids:
            raise ValueError(f"duplicate lesson_id '{lesson_id}'")
        seen_ids.add(lesson_id)
        order.append(lesson_id)

        status = raw["status"]
        for concept_id in raw.get("concepts", []):
            if concept_id not in concepts:
                raise ValueError(
                    f"{lesson_id}: concept '{concept_id}' is not defined in concepts map")
        for category in raw.get("permitted_categories", []):
            if category not in categories:
                raise ValueError(
                    f"{lesson_id}: permitted category '{category}' is not a known "
                    f"policy category {sorted(categories)}")

        budgets = None
        if raw.get("budgets"):
            budgets = Budgets.from_dict(raw["budgets"])
        elif status != "planned":
            raise ValueError(f"{lesson_id}: non-planned lesson must declare budgets")

        lessons[lesson_id] = Lesson(
            lesson_id=lesson_id, title=raw["title"], status=status,
            objective=raw["objective"], concepts=tuple(raw.get("concepts", [])),
            prerequisites=tuple(raw.get("prerequisites", [])),
            in_scope=tuple(raw.get("in_scope", [])),
            out_of_scope=tuple(raw.get("out_of_scope", [])),
            permitted_categories=tuple(raw.get("permitted_categories", [])),
            budgets=budgets,
            completion_criteria=tuple(raw.get("completion_criteria", [])),
        )

    for lesson in lessons.values():
        for prereq in lesson.prerequisites:
            if prereq not in lessons:
                raise ValueError(
                    f"{lesson.lesson_id}: prerequisite '{prereq}' does not exist")

    return Curriculum(concepts=concepts, lessons=lessons, order=tuple(order))
