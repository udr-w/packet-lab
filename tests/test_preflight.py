"""Private preflight: minimal, private, and non-contaminating.

Preflight exists so the assistant can verify the learner's environment before
asking a prediction question — WITHOUT consuming the phenomenon the learner
is about to observe, and without any of it counting as learner evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from packetlab.lab import preflight
from packetlab.lab.curriculum import Budgets, Curriculum, Lesson
from packetlab.lab.profiles import LearnerProfiles
from packetlab.lab.statefile import atomic_write_json


def lesson(categories: tuple, status: str = "in_progress") -> Lesson:
    return Lesson(lesson_id="v3.0", title="DNS fundamentals", status=status,
                  objective="o", concepts=("dns.a",), prerequisites=(),
                  in_scope=(), out_of_scope=(),
                  permitted_categories=categories,
                  budgets=Budgets(30, 3, 2, 300), completion_criteria=())


class PlanDecision(unittest.TestCase):
    def test_conversational_step_needs_no_validation(self):
        plan = preflight.plan(lesson(("dns_query", "capture")),
                              next_phase="observed")
        self.assertFalse(plan["recommended"])
        self.assertEqual(plan["outcome"], "none_needed")

    def test_no_environment_categories_needs_no_validation(self):
        plan = preflight.plan(lesson(("observe_network", "read_system_file")),
                              next_phase="theory")
        self.assertFalse(plan["recommended"])
        self.assertEqual(plan["checks"], [])

    def test_capture_lesson_gets_capability_checks(self):
        plan = preflight.plan(lesson(("capture",)), next_phase="theory")
        self.assertTrue(plan["recommended"])
        self.assertEqual(plan["outcome"], "capability_only")
        ids = [c["id"] for c in plan["checks"]]
        self.assertIn("binary:tcpdump", ids)
        self.assertIn("capability:tcpdump", ids)

    def test_stateful_lesson_upgrades_to_lightweight_with_controls(self):
        plan = preflight.plan(lesson(("dns_query", "capture")),
                              next_phase="predicted")
        self.assertEqual(plan["outcome"], "lightweight")
        self.assertTrue(plan["disposable_hostname"])
        controls = " ".join(plan["contamination_controls"])
        self.assertIn("disposable hostname", controls)
        self.assertIn("after the learner's prediction", controls)
        self.assertIn("never recorded as learner evidence", controls)
        self.assertTrue(plan["residual_risks"],
                        "residual contamination must be declared, not hidden")

    def test_missing_lesson_is_safe(self):
        plan = preflight.plan(None, next_phase="theory")
        self.assertFalse(plan["recommended"])


class NonContamination(unittest.TestCase):
    def test_disposable_hostname_never_matches_reserved(self):
        reserved = ("example.com", "wikipedia.org",
                    "pl-preflight-0000000000.example.com")
        for _ in range(50):
            name = preflight.disposable_hostname(reserved)
            self.assertNotIn(name.lower(), {r.lower() for r in reserved})
            self.assertTrue(name.endswith(".example.com"))

    def test_disposable_hostname_rejects_colliding_token(self):
        name = preflight.disposable_hostname(
            ("pl-preflight-collide.example.com",), token="pl-preflight-collide")
        self.assertNotEqual(name, "pl-preflight-collide.example.com")

    def test_plan_lists_learner_targets_as_forbidden(self):
        plan = preflight.plan(lesson(("dns_query",)), next_phase="theory",
                              reserved_targets=("lesson-target.example.org",))
        self.assertEqual(plan["forbidden_targets"],
                         ["lesson-target.example.org"])
        self.assertNotEqual(plan["disposable_hostname"],
                            "lesson-target.example.org")

    def test_disposable_hostnames_are_unique_per_plan(self):
        names = {preflight.plan(lesson(("dns_query",)),
                                next_phase="theory")["disposable_hostname"]
                 for _ in range(10)}
        self.assertEqual(len(names), 10,
                         "a repeated probe name could itself become a warmed "
                         "cache entry across sessions")


class RunChecks(unittest.TestCase):
    def _fingerprint(self, root: Path) -> dict:
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file()}

    def test_run_checks_touches_no_learner_state(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            profiles = LearnerProfiles(tmp)
            profiles.create("udara")
            ldir = profiles.learner_dir("udara")
            atomic_write_json(ldir / "lesson.json",
                              {"lesson_id": "v3.0", "closed": True,
                               "concept_phase": {"dns.a": "predicted"}})
            atomic_write_json(ldir / "learner.json",
                              {"version": 1, "concepts": {}})
            before = self._fingerprint(tmp)
            plan = preflight.plan(lesson(("dns_query",)), next_phase="theory")
            preflight.run_checks(plan)
            self.assertEqual(before, self._fingerprint(tmp),
                             "preflight must never advance mastery, phase, "
                             "or record evidence")

    def test_run_checks_is_marked_private(self):
        plan = preflight.plan(lesson(("dns_query",)), next_phase="theory")
        results = preflight.run_checks(plan)
        self.assertTrue(results["private"])

    def test_run_checks_reports_missing_binary_as_unavailable(self):
        results = preflight.run_checks(
            {"outcome": "capability_only",
             "checks": [{"id": "binary:definitely-not-installed-xyz",
                         "kind": "binary",
                         "target": "definitely-not-installed-xyz"}]})
        self.assertFalse(results["ok"])
        self.assertEqual(results["outcome"], "unavailable")

    def test_present_binary_passes(self):
        results = preflight.run_checks(
            {"outcome": "capability_only",
             "checks": [{"id": "binary:python3", "kind": "binary",
                         "target": "python3"}]})
        self.assertTrue(results["ok"])


class FailureMessaging(unittest.TestCase):
    def test_failure_message_is_plain_and_honest(self):
        results = preflight.run_checks(
            {"outcome": "capability_only",
             "checks": [{"id": "binary:tcpdump", "kind": "binary",
                         "target": "definitely-not-installed-tcpdump"}]})
        message = preflight.learner_message_for_failure(results)
        self.assertTrue(message)
        self.assertNotIn("getcap", message)
        self.assertNotIn("cap_net_raw", message)
        self.assertNotIn("/usr/bin", message)
        self.assertNotIn("exit code", message)
        self.assertIn("hasn't lost any progress", message)

    def test_no_failure_means_no_message(self):
        self.assertEqual("", preflight.learner_message_for_failure(
            {"results": [{"id": "x", "ok": True, "target": "dig"}]}))

    def test_preflight_results_never_appear_in_learner_snapshot_view(self):
        # The learner renderer consumes the snapshot; run_checks output is a
        # separate private payload that the renderer never receives. Guard the
        # boundary: the plan embedded in a snapshot stays out of learner text.
        from packetlab.lab import resume as resume_mod
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            profiles = LearnerProfiles(tmp)
            profiles.create("udara")
            atomic_write_json(profiles.learner_dir("udara") / "lesson.json",
                              {"lesson_id": "v3.0", "closed": True,
                               "concept_phase": {"dns.a": "theory"}})
            curric = Curriculum(concepts={"dns.a": "A"},
                                lessons={"v3.0": lesson(("dns_query",
                                                         "capture"))},
                                order=("v3.0",))
            snapshot = resume_mod.build_snapshot(state_dir=tmp,
                                                 curriculum=curric)
            text = resume_mod.render_learner(snapshot)
            self.assertNotIn(snapshot["preflight"].get("disposable_hostname",
                                                       "\x00"), text)
            self.assertNotIn("tcpdump", text)
            self.assertNotIn("contamination", text)


if __name__ == "__main__":
    unittest.main()
