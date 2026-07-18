"""Local learner profiles and per-learner state isolation.

Packet Lab is a multi-learner product: any engineer can run the repository and
receive lessons tailored to their own mastery. One learner's state must never
silently become another's starting point, so all live learner-specific state is
namespaced by a validated learner id:

    state/
      active-learner                       # id of the currently selected learner
      learners/<id>/
        profile.json                       # id, display name, created_at, prefs
        lesson.json                        # governor state (current lesson/phase)
        learner.json                       # concept mastery + evidence
        runs/<run-id>/trace.jsonl          # traces containing this learner's answers
        workspace/<run-id>/                # guarded-command working dir
        tools/                             # generated tools (learner-local)

Shared, non-learner state (curriculum definitions, the built-in tool registry,
evaluation fixtures, committed examples) lives outside `learners/` and is never
copied into a new learner's active context.

This is local profile isolation, not authentication: anyone with access to the
state directory can read any local profile. Hosted multi-tenant security is out
of scope (see docs/threat-model.md and the README limitations).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import shutil
from pathlib import Path

from packetlab.lab.statefile import atomic_write_json, load_json

PROFILE_SCHEMA_VERSION = 1
ACTIVE_FILE = "active-learner"
LEARNERS_DIR = "learners"

# A learner id must be a safe, normalised, filesystem-friendly slug.
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Names that would collide with layout files or confuse path resolution.
_RESERVED = {
    ".", "..", "shared", "learners", "active-learner", "runs", "workspace",
    "tools", "state", "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def validate_learner_id(raw) -> tuple[str | None, str]:
    """Normalise and validate a learner id. Returns (id, "") or (None, reason)."""
    if not isinstance(raw, str):
        return None, "learner id must be a string"
    candidate = raw.strip().lower()
    if not candidate:
        return None, "learner id must not be empty"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in candidate):
        return None, "learner id must not contain control characters"
    if "/" in candidate or "\\" in candidate or "\x00" in candidate:
        return None, "learner id must not contain path separators"
    if ".." in candidate or candidate.startswith("."):
        return None, "learner id must not contain traversal sequences"
    if candidate in _RESERVED:
        return None, f"'{candidate}' is a reserved name"
    if not _ID_PATTERN.match(candidate):
        return None, ("learner id must be 1-63 chars of a-z, 0-9, '-' or '_', "
                      "starting with a letter or digit")
    return candidate, ""


@dataclass(frozen=True)
class Profile:
    learner_id: str
    display_name: str
    created_at: str
    preferences: dict
    schema_version: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LearnerProfiles:
    """Manager for local learner profiles under a state directory."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.learners_dir = state_dir / LEARNERS_DIR
        self.active_path = state_dir / ACTIVE_FILE

    # ---- layout -----------------------------------------------------------

    def learner_dir(self, learner_id: str) -> Path:
        norm, err = validate_learner_id(learner_id)
        if norm is None:
            raise ValueError(f"invalid learner id: {err}")
        return self.learners_dir / norm

    def profile_path(self, learner_id: str) -> Path:
        return self.learner_dir(learner_id) / "profile.json"

    def exists(self, learner_id: str) -> bool:
        norm, err = validate_learner_id(learner_id)
        if norm is None:
            return False
        return (self.learners_dir / norm / "profile.json").exists()

    # ---- lifecycle --------------------------------------------------------

    def create(self, learner_id: str, display_name: str | None = None) -> Profile:
        norm, err = validate_learner_id(learner_id)
        if norm is None:
            raise ValueError(err)
        if self.exists(norm):
            raise ValueError(f"learner '{norm}' already exists")
        directory = self.learners_dir / norm
        (directory / "runs").mkdir(parents=True, exist_ok=True)
        profile = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "learner_id": norm,
            "display_name": (display_name or norm)[:80],
            "created_at": _now(),
            "preferences": {},
        }
        atomic_write_json(directory / "profile.json", profile)
        if self.get_active() is None:
            self.set_active(norm)
        return self._to_profile(profile)

    def list(self) -> list[str]:
        if not self.learners_dir.is_dir():
            return []
        return sorted(entry.name for entry in self.learners_dir.iterdir()
                      if (entry / "profile.json").exists())

    def profile(self, learner_id: str) -> Profile | None:
        path = self.profile_path(learner_id)
        if not path.exists():
            return None
        return self._to_profile(load_json(path))

    def get_active(self) -> str | None:
        if not self.active_path.exists():
            return None
        raw = self.active_path.read_text(encoding="utf-8").strip()
        norm, err = validate_learner_id(raw)
        if norm is None or not self.exists(norm):
            return None
        return norm

    def set_active(self, learner_id: str) -> str:
        norm, err = validate_learner_id(learner_id)
        if norm is None:
            raise ValueError(err)
        if not self.exists(norm):
            raise ValueError(f"unknown learner '{norm}'")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.active_path.write_text(norm + "\n", encoding="utf-8")
        return norm

    def reset(self, learner_id: str) -> None:
        """Wipe a learner's live state, preserving the profile identity."""
        norm, err = validate_learner_id(learner_id)
        if norm is None:
            raise ValueError(err)
        if not self.exists(norm):
            raise ValueError(f"unknown learner '{norm}'")
        directory = self.learners_dir / norm
        prof = load_json(directory / "profile.json")
        for child in ("lesson.json", "learner.json"):
            (directory / child).unlink(missing_ok=True)
        for sub in ("runs", "workspace", "tools"):
            shutil.rmtree(directory / sub, ignore_errors=True)
        (directory / "runs").mkdir(parents=True, exist_ok=True)
        atomic_write_json(directory / "profile.json", prof)

    def delete(self, learner_id: str) -> None:
        norm, err = validate_learner_id(learner_id)
        if norm is None:
            raise ValueError(err)
        shutil.rmtree(self.learners_dir / norm, ignore_errors=True)
        if self.get_active() == norm:
            self.active_path.unlink(missing_ok=True)

    # ---- legacy migration -------------------------------------------------

    def migrate_legacy_if_present(self) -> str | None:
        """Move pre-multi-learner global state into a `default` profile.

        Compatibility rule (documented in docs/operational-runbook.md): a legacy
        single-user install kept state at state/lesson.json + state/learner.json.
        On first use those are migrated into a clearly named `default` learner —
        never silently promoted to a global learner. Returns the id if migrated.
        """
        legacy_lesson = self.state_dir / "lesson.json"
        legacy_learner = self.state_dir / "learner.json"
        if self.learners_dir.exists() or not (legacy_lesson.exists()
                                              or legacy_learner.exists()):
            return None
        directory = self.learners_dir / "default"
        (directory / "runs").mkdir(parents=True, exist_ok=True)
        atomic_write_json(directory / "profile.json", {
            "schema_version": PROFILE_SCHEMA_VERSION, "learner_id": "default",
            "display_name": "default (migrated)", "created_at": _now(),
            "preferences": {}, "migrated_from": "legacy-single-user-state"})
        if legacy_lesson.exists():
            legacy_lesson.replace(directory / "lesson.json")
        if legacy_learner.exists():
            legacy_learner.replace(directory / "learner.json")
        legacy_runs = self.state_dir / "runs"
        if legacy_runs.is_dir():
            legacy_runs.replace(directory / "runs")
        self.set_active("default")
        return "default"

    @staticmethod
    def _to_profile(data: dict) -> Profile:
        return Profile(
            learner_id=data["learner_id"],
            display_name=data.get("display_name", data["learner_id"]),
            created_at=data.get("created_at", ""),
            preferences=data.get("preferences", {}),
            schema_version=data.get("schema_version", PROFILE_SCHEMA_VERSION),
        )
