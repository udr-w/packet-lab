"""Proportional session close: repository mutation matches durable value.

Pins the judgment that was previously missing: a session that produced no
learning evidence must end with an aborted run in learner state and NOTHING
else — no documentation, no commit, no push, no growth. Meaningful sessions
earn exactly the writes their class allows.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from packetlab.lab import closeout
from packetlab.lab.curriculum import load as load_curriculum
from packetlab.lab.governor import Governor
from packetlab.lab.profiles import LearnerProfiles
from packetlab.lab.trace import Trace, new_run_id

REPO = Path(__file__).resolve().parents[1]


def record_event(phase: str) -> dict:
    return {"component": "governor", "event": "action_committed",
            "kind": "record", "phase": phase}


class Classification(unittest.TestCase):
    def test_no_op_session(self):
        result = closeout.classify([])
        self.assertEqual(result["class"], "no_op")

    def test_unanswered_question_is_no_op(self):
        # Resumed, question posed, learner left. Trace has governor decisions
        # but no record commits.
        events = [{"component": "governor", "event": "lesson_started"},
                  {"component": "governor", "event": "policy_decision"}]
        self.assertEqual(closeout.classify(events)["class"], "no_op")

    def test_skip_waivers_alone_are_not_evidence(self):
        events = [record_event("skip"), record_event("skip")]
        result = closeout.classify(events)
        self.assertEqual(result["class"], "no_op")
        self.assertEqual(result["skips"], 2)

    def test_prediction_makes_evidence_session(self):
        result = closeout.classify([record_event("predicted")])
        self.assertEqual(result["class"], "evidence")

    def test_observation_and_explanation_make_evidence_session(self):
        events = [record_event("predicted"), record_event("observed"),
                  record_event("explained")]
        result = closeout.classify(events)
        self.assertEqual(result["class"], "evidence")
        self.assertEqual(result["evidence_events"], 3)

    def test_closed_lesson_is_milestone(self):
        events = [record_event("explained"),
                  {"component": "governor", "event": "lesson_closed"}]
        self.assertEqual(closeout.classify(events)["class"], "milestone")

    def test_engineering_changes_detected_and_state_ignored(self):
        result = closeout.classify(
            [], changed_repo_files=("state/learners/udara/lesson.json",
                                    "packetlab/lab/resume.py"))
        self.assertEqual(result["engineering_changes"],
                         ["packetlab/lab/resume.py"])


class PersistencePolicy(unittest.TestCase):
    def test_no_op_writes_nothing(self):
        policy = closeout.persistence_policy(closeout.classify([]))
        for key in ("lesson_narrative", "task_md", "handover", "knowledge",
                    "roadmap", "commit", "push"):
            self.assertFalse(policy[key], key)

    def test_evidence_commits_locally_but_never_pushes(self):
        policy = closeout.persistence_policy(
            closeout.classify([record_event("predicted")]))
        self.assertTrue(policy["lesson_narrative"])
        self.assertTrue(policy["commit"])
        self.assertFalse(policy["push"])
        self.assertFalse(policy["handover"])

    def test_milestone_gets_the_full_wrapup(self):
        policy = closeout.persistence_policy(closeout.classify(
            [{"component": "governor", "event": "lesson_closed"}]))
        for key in ("lesson_narrative", "task_md", "handover", "knowledge",
                    "roadmap", "commit", "push"):
            self.assertTrue(policy[key], key)

    def test_learner_privacy_note_always_present(self):
        for events in ([], [record_event("predicted")]):
            policy = closeout.persistence_policy(closeout.classify(events))
            self.assertTrue(any("learner-private" in n
                                for n in policy["notes"]))

    def test_farewell_is_short_and_jargon_free(self):
        for events in ([], [record_event("predicted")]):
            message = closeout.learner_farewell(closeout.classify(events))
            self.assertLess(len(message), 200)
            for term in ("run", "trace", "governor", "abort", "state",
                         "commit"):
                self.assertNotIn(term, message.lower())


class EndToEndClose(unittest.TestCase):
    """Drive `lesson end` through the real CLI in an isolated state dir."""

    def run_lab(self, state_dir: Path, *argv: str):
        env = dict(os.environ, PACKETLAB_STATE=str(state_dir))
        return subprocess.run(["python3", "-m", "packetlab.lab", *argv],
                              capture_output=True, text=True, cwd=REPO,
                              env=env, timeout=30)

    def fingerprint(self, root: Path, skip: tuple = ()) -> dict:
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*"))
                if p.is_file() and not any(s in str(p) for s in skip)}

    def test_no_op_close_touches_only_lesson_state(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.run_lab(state, "learner", "create", "u1")
            self.run_lab(state, "lesson", "start", "v3.0")
            docs_before = self.fingerprint(REPO / "docs")
            task_before = (REPO / "TASK.md").read_bytes()
            proc = self.run_lab(state, "lesson", "end", "--reason",
                                "I have to go")
            out = json.loads(proc.stdout)
            self.assertEqual(out["session"]["class"], "no_op")
            self.assertFalse(out["persistence"]["commit"])
            # Repository documentation untouched by the close itself.
            self.assertEqual(docs_before, self.fingerprint(REPO / "docs"))
            self.assertEqual(task_before, (REPO / "TASK.md").read_bytes())

    def test_resume_after_no_op_close_returns_same_question(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.run_lab(state, "learner", "create", "u1")
            before = json.loads(
                self.run_lab(state, "resume", "--json").stdout)
            self.run_lab(state, "lesson", "start", "v3.0")
            self.run_lab(state, "lesson", "end", "--reason", "gtg")
            after = json.loads(self.run_lab(state, "resume", "--json").stdout)
            self.assertEqual(before["next"]["prompt"], after["next"]["prompt"])
            self.assertEqual(after["next"]["concept"], "dns.resolution-chain")

    def test_repeated_open_close_cycles_do_not_grow_state_or_docs(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.run_lab(state, "learner", "create", "u1")
            sizes = []
            for _ in range(5):
                self.run_lab(state, "lesson", "start", "v3.0")
                self.run_lab(state, "lesson", "end", "--reason", "gtg")
                sizes.append(
                    (state / "learners" / "u1" / "lesson.json").stat().st_size)
            # lesson.json is rewritten fresh each start: bounded, not a diary.
            self.assertLess(max(sizes), 2 * min(sizes) + 512)

    def test_end_with_nothing_open_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.run_lab(state, "learner", "create", "u1")
            proc = self.run_lab(state, "lesson", "end")
            out = json.loads(proc.stdout)
            self.assertEqual(out["session"]["class"], "no_op")
            self.assertIn("nothing to close", out["note"])

    def test_two_learners_close_concurrently_without_cross_writes(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.run_lab(state, "learner", "create", "u1")
            self.run_lab(state, "learner", "create", "u2")
            self.run_lab(state, "learner", "use", "u1")
            self.run_lab(state, "lesson", "start", "v3.0")
            u2_before = self.fingerprint(state / "learners" / "u2")
            self.run_lab(state, "lesson", "end", "--reason", "gtg")
            self.assertEqual(u2_before,
                             self.fingerprint(state / "learners" / "u2"))
            self.run_lab(state, "learner", "use", "u2")
            proc = self.run_lab(state, "lesson", "end")
            self.assertEqual(json.loads(proc.stdout)["learner"], "u2")


class CloseProtocolConsistency(unittest.TestCase):
    """Natural-language close must find the same one-command protocol."""

    def test_end_lesson_skill_exists_and_matches_cli(self):
        skill = (REPO / ".claude" / "skills" / "end-lesson"
                 / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("./packet-lab.sh lesson end", skill)
        self.assertIn("I have to go", skill)
        # The learner is released before any documentation or git work.
        self.assertLess(skill.index("Release the learner"),
                        skill.index("follow the printed policy"))

    def test_shell_alias_forwards_to_lesson_end(self):
        script = (REPO / "packet-lab.sh").read_text(encoding="utf-8")
        self.assertIn("close|end)", script)
        self.assertIn("lesson end", script)

    def test_close_alias_works_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            env = dict(os.environ, PACKETLAB_STATE=str(state))
            subprocess.run([str(REPO / "packet-lab.sh"), "resume"],
                           capture_output=True, cwd=REPO, env=env, timeout=30)
            subprocess.run(["python3", "-m", "packetlab.lab", "learner",
                            "create", "u1"], capture_output=True, cwd=REPO,
                           env=env, timeout=30)
            proc = subprocess.run(
                [str(REPO / "packet-lab.sh"), "close", "--reason", "gtg"],
                capture_output=True, text=True, cwd=REPO, env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["session"]["class"],
                             "no_op")


class MeaningfulProgressPreserved(unittest.TestCase):
    def test_evidence_session_keeps_evidence_in_canonical_state(self):
        # A full predict->observe->explain cycle lands in the learner model
        # and the governor phase machine — no documentation copy required
        # for the next resume to be correct.
        from packetlab.lab.learner import LearnerModel
        from packetlab.lab import resume as resume_mod
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            profiles = LearnerProfiles(state)
            profiles.create("u1")
            ldir = profiles.learner_dir("u1")
            run_id = new_run_id()
            trace = Trace(run_id, "v3.0", base_dir=ldir, learner_id="u1")
            gov = Governor(load_curriculum(), trace=trace,
                           state_path=ldir / "lesson.json")
            gov.start_lesson("v3.0", run_id)
            model = LearnerModel(ldir / "learner.json")
            from packetlab.lab.governor import Action
            for phase, kind in (("predicted", "prediction"),
                                ("observed", "observation"),
                                ("explained", "explanation")):
                action = Action("record", concept_id="dns.resolution-chain",
                                phase=phase)
                self.assertTrue(gov.evaluate(action).allowed)
                gov.commit(action)
                model.add_evidence("dns.resolution-chain", kind,
                                   f"u1 {kind}", "v3.0", run_id)
            gov.abort_lesson("end of session")

            from packetlab.lab.trace import read_trace, runs_dir
            events = read_trace(runs_dir(ldir) / run_id / "trace.jsonl")
            classification = closeout.classify(events)
            self.assertEqual(classification["class"], "evidence")
            self.assertEqual(
                model.concept("dns.resolution-chain").state, "mastered")
            snapshot = resume_mod.build_snapshot(state_dir=state)
            self.assertEqual(snapshot["next"]["concept"],
                             "dns.configuration-vs-cache")


if __name__ == "__main__":
    unittest.main()
