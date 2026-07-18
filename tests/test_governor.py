"""Curriculum Governor — drift prevention, phase gates, budgets, two-phase commit."""

import tempfile
import unittest
from pathlib import Path

from packetlab.lab import curriculum as curriculum_mod
from packetlab.lab.governor import Action, Governor
from packetlab.lab.trace import Trace, new_run_id, verify_chain


class GovernorBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.curric = curriculum_mod.load()
        self.run_id = new_run_id()
        self.trace = Trace(self.run_id, "v3.0", base_dir=self.tmp)
        self.gov = Governor(self.curric, trace=self.trace,
                            state_path=self.tmp / "state" / "lesson.json")

    def tearDown(self):
        self._tmp.cleanup()

    def start(self, lesson_id="v3.0"):
        self.gov.start_lesson(lesson_id, self.run_id)


class Drift(GovernorBase):
    def test_out_of_scope_topic_denied(self):
        self.start()
        self.assertFalse(self.gov.evaluate(Action("topic", concept_id="tcp")).allowed)

    def test_in_scope_topic_allowed(self):
        self.start()
        self.assertTrue(self.gov.evaluate(
            Action("topic", concept_id="dns.udp-53")).allowed)

    def test_command_category_not_permitted_denied(self):
        self.start()
        # ARP cache mutation is not permitted in the DNS lesson.
        d = self.gov.evaluate(Action("run_command", category="modify_neighbour_cache"))
        self.assertFalse(d.allowed)

    def test_permitted_category_allowed(self):
        self.start()
        self.assertTrue(self.gov.evaluate(
            Action("run_command", category="dns_query")).allowed)


class Phases(GovernorBase):
    def test_observe_before_predict_denied(self):
        self.start()
        d = self.gov.evaluate(Action("record", concept_id="dns.udp-53",
                                     phase="observed"))
        self.assertFalse(d.allowed)
        self.assertEqual(d.rule, "predict-before-observe")

    def test_predict_then_observe_then_explain(self):
        self.start()
        for phase in ("predicted", "observed", "explained"):
            action = Action("record", concept_id="dns.udp-53", phase=phase)
            self.assertTrue(self.gov.evaluate(action).allowed, phase)
            self.gov.commit(action)

    def test_skip_waiver_satisfies_gate(self):
        self.start()
        skip = Action("record", concept_id="dns.udp-53", phase="skip")
        self.assertTrue(self.gov.evaluate(skip).allowed)
        self.gov.commit(skip)
        # After a skip, an observation is allowed (the gate is satisfied).
        obs = Action("record", concept_id="dns.udp-53", phase="observed")
        self.assertTrue(self.gov.evaluate(obs).allowed)


class Budgets(GovernorBase):
    def test_step_budget_stops_further_commands(self):
        self.start()
        lesson = self.curric.lesson("v3.0")
        action = Action("run_command", category="dns_query")
        for _ in range(lesson.budgets.max_steps):
            self.gov.commit(action, outcome={"status": "ok", "duration_ms": 10})
        self.assertFalse(self.gov.evaluate(action).allowed)
        state = self.gov.status()
        self.assertTrue(any("steps-budget" in s.get("marker", "")
                            for s in state["stop_reasons"]))

    def test_tool_budget(self):
        self.start()
        lesson = self.curric.lesson("v3.0")
        gen = Action("generate_tool")
        for _ in range(lesson.budgets.max_generated_tools):
            self.gov.commit(gen)
        self.assertFalse(self.gov.evaluate(gen).allowed)

    def test_denied_action_consumes_no_budget(self):
        self.start()
        before = self.gov.status()["counters"]["steps"]
        self.gov.evaluate(Action("run_command", category="modify_neighbour_cache"))
        after = self.gov.status()["counters"]["steps"]
        self.assertEqual(before, after)


class Lifecycle(GovernorBase):
    def test_cannot_start_planned_lesson(self):
        with self.assertRaises(ValueError):
            self.gov.start_lesson("v4.0", self.run_id)

    def test_close_requires_completion_criteria(self):
        self.start()
        with self.assertRaises(ValueError):
            self.gov.close_lesson([])

    def test_no_active_lesson_denies(self):
        d = self.gov.evaluate(Action("run_command", category="dns_query"))
        self.assertFalse(d.allowed)
        self.assertEqual(d.rule, "no-lesson")

    def test_every_decision_is_traced_and_chain_verifies(self):
        self.start()
        self.gov.evaluate(Action("topic", concept_id="tcp"))
        self.gov.evaluate(Action("run_command", category="dns_query"))
        ok, problems = verify_chain(self.trace.path)
        self.assertTrue(ok, problems)


if __name__ == "__main__":
    unittest.main()
