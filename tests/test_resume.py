"""Resume snapshot guarantees: read-only, isolated, quiet, and correct.

These tests pin the properties that make `packet-lab.sh resume` safe to run
as the first (and normally only) call of a lesson resume:

- strictly read-only (no state mutation, no run creation, no migration)
- no network, no subprocesses (so no tcpdump/dig/ping/getcap, no doctor,
  no tests/evals — nothing that could be slow or contaminate the lesson)
- reads only the ACTIVE learner's state
- returns clear statuses for no-learner / nothing-in-progress
- default learner output carries no operational machinery
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

from packetlab.lab import resume as resume_mod
from packetlab.lab.curriculum import Budgets, Curriculum, Lesson
from packetlab.lab.profiles import LearnerProfiles
from packetlab.lab.statefile import atomic_write_json

REPO = Path(__file__).resolve().parents[1]


def make_curriculum() -> Curriculum:
    lesson = Lesson(
        lesson_id="v3.0", title="DNS fundamentals", status="in_progress",
        objective="Understand how names become IP addresses.",
        concepts=("dns.resolution-chain", "dns.caching-ttl"),
        prerequisites=(), in_scope=(), out_of_scope=(),
        permitted_categories=("observe_network", "dns_query", "capture"),
        budgets=Budgets(30, 3, 2, 300),
        completion_criteria=("Student explains the chain",),
        prompts={"dns.resolution-chain": {
            "predict": "Does a fresh machine know any DNS answers, and whom "
                       "to ask? Where would each come from?",
            "observe": "Run dig twice while capturing UDP 53 and describe "
                       "what the radio carries each time."}})
    return Curriculum(
        concepts={"dns.resolution-chain": "Who asks whom and why",
                  "dns.caching-ttl": "Caching and TTLs"},
        lessons={"v3.0": lesson}, order=("v3.0",))


def make_state(tmp: Path, learner: str = "udara", *, lesson_state: dict | None,
               learner_model: dict | None = None) -> Path:
    profiles = LearnerProfiles(tmp)
    profiles.create(learner)
    ldir = profiles.learner_dir(learner)
    if lesson_state is not None:
        atomic_write_json(ldir / "lesson.json", lesson_state)
    if learner_model is not None:
        atomic_write_json(ldir / "learner.json", learner_model)
    return tmp


UNFINISHED_LESSON = {
    "lesson_id": "v3.0", "run_id": "run-20260718-125634-fac679",
    "closed": True, "aborted": True,
    "concept_phase": {"dns.resolution-chain": "predicted",
                      "dns.caching-ttl": "theory"},
    "stop_reasons": [{"ts": "2026-07-18T13:27:28+00:00",
                      "reason": "Student had to leave; no evidence recorded. "
                                "Resume v3.0 at step 1."}],
}

MODEL_WITH_PREDICTION = {
    "version": 1,
    "concepts": {"dns.resolution-chain": {
        "state": "in_progress", "updated_at": "2026-07-04T20:00:00+00:00",
        "evidence": [{"ts": "2026-07-04T20:00:00+00:00", "kind": "prediction",
                      "summary": "the second lookup is answered from cache",
                      "lesson_id": "v3.0", "run_id": "run-x"}]}},
}


def dir_fingerprint(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class SnapshotSideEffects(unittest.TestCase):
    def build(self, tmp: Path) -> dict:
        return resume_mod.build_snapshot(state_dir=tmp,
                                         curriculum=make_curriculum())

    def test_snapshot_is_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON,
                             learner_model=MODEL_WITH_PREDICTION)
            before = dir_fingerprint(tmp)
            self.build(tmp)
            self.assertEqual(before, dir_fingerprint(tmp),
                             "resume snapshot must not create/modify/delete "
                             "any file (mastery, governor state, runs, locks)")

    def test_snapshot_creates_no_lesson_run(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            runs = tmp / "learners" / "udara" / "runs"
            before = sorted(runs.iterdir()) if runs.exists() else []
            self.build(tmp)
            after = sorted(runs.iterdir()) if runs.exists() else []
            self.assertEqual(before, after)

    def test_snapshot_makes_no_network_calls(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            with mock.patch.object(socket, "socket",
                                   side_effect=AssertionError("network call")), \
                 mock.patch.object(socket, "create_connection",
                                   side_effect=AssertionError("network call")), \
                 mock.patch.object(socket, "getaddrinfo",
                                   side_effect=AssertionError("dns lookup")):
                snapshot = self.build(tmp)
            self.assertEqual(snapshot["status"], "resume")

    def test_snapshot_spawns_no_subprocesses(self):
        # Blocks tcpdump/dig/ping/getcap AND doctor/tests/evals wholesale:
        # none of them can run if no subprocess can start.
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            with mock.patch.object(subprocess, "Popen",
                                   side_effect=AssertionError("subprocess")), \
                 mock.patch.object(subprocess, "run",
                                   side_effect=AssertionError("subprocess")), \
                 mock.patch("os.system",
                            side_effect=AssertionError("os.system")):
                snapshot = self.build(tmp)
            self.assertEqual(snapshot["status"], "resume")

    def test_snapshot_does_not_migrate_legacy_state(self):
        # Legacy single-user files must be left exactly where they are.
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            atomic_write_json(tmp / "lesson.json", {"lesson_id": "v3.0"})
            before = dir_fingerprint(tmp)
            snapshot = self.build(tmp)
            self.assertEqual(snapshot["status"], "no_active_learner")
            self.assertEqual(before, dir_fingerprint(tmp))


class SnapshotIsolation(unittest.TestCase):
    def test_reads_only_active_learner(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            profiles = LearnerProfiles(tmp)
            profiles.create("udara")
            profiles.create("other")
            atomic_write_json(profiles.learner_dir("udara") / "lesson.json",
                              UNFINISHED_LESSON)
            atomic_write_json(
                profiles.learner_dir("other") / "learner.json",
                {"version": 1, "concepts": {"dns.caching-ttl": {
                    "state": "mastered", "updated_at": "x",
                    "evidence": [{"ts": "x", "kind": "explanation",
                                  "summary": "OTHER-LEARNER-PRIVATE-EVIDENCE",
                                  "lesson_id": "v3.0", "run_id": None}]}}})
            profiles.set_active("udara")
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            blob = json.dumps(snapshot)
            self.assertNotIn("OTHER-LEARNER-PRIVATE-EVIDENCE", blob)
            self.assertNotIn("/other", blob)
            self.assertEqual(snapshot["learner"]["id"], "udara")

    def test_valid_after_learner_switch(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            profiles = LearnerProfiles(tmp)
            profiles.create("udara")
            profiles.create("fresh")
            atomic_write_json(profiles.learner_dir("udara") / "lesson.json",
                              UNFINISHED_LESSON)
            profiles.set_active("udara")
            first = resume_mod.build_snapshot(state_dir=tmp,
                                              curriculum=make_curriculum())
            profiles.set_active("fresh")
            second = resume_mod.build_snapshot(state_dir=tmp,
                                               curriculum=make_curriculum())
            self.assertEqual(first["learner"]["id"], "udara")
            self.assertEqual(first["status"], "resume")
            self.assertEqual(second["learner"]["id"], "fresh")
            self.assertEqual(second["status"], "fresh")
            self.assertEqual([], resume_mod.validate_snapshot(second))

    def test_isolated_state_dir_is_sufficient(self):
        # The snapshot needs ONLY the state dir + curriculum: committed
        # example traces and docs are structurally out of reach.
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            self.assertEqual([], resume_mod.validate_snapshot(snapshot))
            self.assertNotIn("docs/examples", json.dumps(snapshot))


class SnapshotCorrectness(unittest.TestCase):
    def test_unfinished_phase_reported_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON,
                             learner_model=MODEL_WITH_PREDICTION)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            self.assertEqual(snapshot["next"]["concept"], "dns.resolution-chain")
            self.assertEqual(snapshot["next"]["phase"], "predicted")
            self.assertIn("observe", snapshot["next"]["action"])
            self.assertEqual(snapshot["open_prediction"]["summary"],
                             "the second lookup is answered from cache")

    def test_no_active_learner_is_clear(self):
        with tempfile.TemporaryDirectory() as d:
            snapshot = resume_mod.build_snapshot(state_dir=Path(d),
                                                 curriculum=make_curriculum())
            self.assertEqual(snapshot["status"], "no_active_learner")
            self.assertTrue(snapshot["message"])
            self.assertEqual([], resume_mod.validate_snapshot(snapshot))

    def test_nothing_in_progress_is_clear(self):
        complete = Lesson(
            lesson_id="v1.1", title="ICMP", status="complete", objective="o",
            concepts=("icmp.a",), prerequisites=(), in_scope=(),
            out_of_scope=(), permitted_categories=("ping",),
            budgets=Budgets(25, 3, 2, 300), completion_criteria=())
        curric = Curriculum(concepts={"icmp.a": "A"},
                            lessons={"v1.1": complete}, order=("v1.1",))
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=None)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=curric)
            self.assertEqual(snapshot["status"], "all_complete")
            self.assertTrue(snapshot["message"])

    def test_fresh_learner_gets_first_startable_lesson(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=None)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            self.assertEqual(snapshot["status"], "fresh")
            self.assertEqual(snapshot["lesson"]["id"], "v3.0")

    def test_snapshot_matches_declared_schema(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            self.assertEqual([], resume_mod.validate_snapshot(snapshot))

    def test_snapshot_is_self_sufficient_no_doc_read_needed(self):
        # The complete next learner question comes from curriculum metadata
        # (or a deterministic fallback) — never from TASK.md or a narrative.
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            # phase 'predicted' -> the authored observe prompt
            self.assertEqual(snapshot["next"]["action_type"], "observe")
            self.assertIn("dig twice", snapshot["next"]["prompt"])
            self.assertEqual(snapshot["preflight"]["timing"], "needed_now")

    def test_conceptual_next_step_defers_preflight(self):
        state = dict(UNFINISHED_LESSON,
                     concept_phase={"dns.resolution-chain": "theory",
                                    "dns.caching-ttl": "theory"})
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=state)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            self.assertEqual(snapshot["next"]["action_type"], "predict")
            self.assertEqual(snapshot["preflight"]["timing"],
                             "needed_before_experiment")
            self.assertFalse(snapshot["preflight"]["recommended"])

    def test_fallback_prompt_when_lesson_has_none_authored(self):
        state = dict(UNFINISHED_LESSON,
                     concept_phase={"dns.resolution-chain": "explained",
                                    "dns.caching-ttl": "theory"})
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=state)
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=make_curriculum())
            self.assertEqual(snapshot["next"]["concept"], "dns.caching-ttl")
            self.assertTrue(snapshot["next"]["prompt"])
            self.assertIn("Caching and TTLs", snapshot["next"]["prompt"])


class OutputSeparation(unittest.TestCase):
    def snapshot(self, tmp: Path) -> dict:
        return resume_mod.build_snapshot(state_dir=tmp,
                                         curriculum=make_curriculum())

    def test_learner_output_has_no_operational_machinery(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON,
                             learner_model=MODEL_WITH_PREDICTION)
            text = resume_mod.render_learner(self.snapshot(tmp))
            for term in ("run-2026", "run_id", "state/learners", "/home/",
                         "doctor", "getcap", "cap_net_raw", "trace",
                         "preflight", "governor", "diagnostic", ".json"):
                self.assertNotIn(term, text,
                                 f"learner output leaked operational term {term!r}")

    def test_learner_output_has_exactly_one_question(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            snapshot = self.snapshot(tmp)
            text = resume_mod.render_learner(snapshot)
            # The prompt is the question, appears once, and closes the message.
            self.assertEqual(text.count(snapshot["next"]["prompt"]), 1)
            self.assertTrue(text.endswith(snapshot["next"]["prompt"]))

    def test_learner_output_is_second_person(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            text = resume_mod.render_learner(self.snapshot(tmp))
            self.assertIn("You", text)
            self.assertNotIn("Student", text)
            self.assertNotIn("the learner", text)

    def test_learner_output_never_mentions_validation(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            text = resume_mod.render_learner(self.snapshot(tmp)).lower()
            for phrase in ("preflight", "capability", "tools available",
                           "state loaded", "run opened", "check passed"):
                self.assertNotIn(phrase, text)

    def test_learner_output_does_not_dump_roadmap(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            text = resume_mod.render_learner(self.snapshot(tmp))
            for later in ("v4.0", "TCP", "TLS", "roadmap"):
                self.assertNotIn(later, text)

    def test_verbose_output_exposes_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = make_state(Path(d), lesson_state=UNFINISHED_LESSON)
            text = resume_mod.render_verbose(self.snapshot(tmp))
            self.assertIn("run-20260718-125634-fac679", text)
            self.assertIn("learner_state_source", text)
            self.assertIn("preflight", text)
            self.assertIn("not for the learner", text)


class CliIntegration(unittest.TestCase):
    def test_cli_resume_json_is_valid_and_quiet(self):
        proc = subprocess.run(
            ["python3", "-m", "packetlab.lab", "resume", "--json"],
            capture_output=True, text=True, cwd=REPO, timeout=30)
        snapshot = json.loads(proc.stdout)
        self.assertEqual([], resume_mod.validate_snapshot(snapshot))

    def test_cli_default_output_has_no_run_id_or_path(self):
        proc = subprocess.run(
            ["python3", "-m", "packetlab.lab", "resume"],
            capture_output=True, text=True, cwd=REPO, timeout=30)
        self.assertNotIn("run-", proc.stdout)
        self.assertNotIn("state/learners", proc.stdout)


class ProtocolConsistency(unittest.TestCase):
    """Natural-language and slash-command resume must be the same protocol."""

    def test_agents_md_and_skill_share_the_protocol(self):
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        skill = (REPO / ".claude" / "skills" / "resume-lesson"
                 / "SKILL.md").read_text(encoding="utf-8")
        for doc in (agents, skill):
            self.assertIn("./packet-lab.sh resume --json", doc)
        self.assertIn("resume-lesson", agents)
        self.assertIn("natural language", skill)

    def test_skill_acknowledges_before_any_tool_call(self):
        skill = (REPO / ".claude" / "skills" / "resume-lesson"
                 / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(skill.index("Acknowledge first"),
                        skill.index("resume --json"),
                        "acknowledgement must precede the snapshot call, so "
                        "a slow preflight can never delay it")
        normalized = " ".join(skill.lower().split())
        self.assertIn("never invent expected results", normalized)
        self.assertIn("needed_before_experiment", skill)


if __name__ == "__main__":
    unittest.main()
