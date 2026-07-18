"""Integration: a real lesson slice driven through the CLI helper layer.

Guards the bug found during review: `run --observation-concept` recorded the
observation in the learner model but not the governor phase, so a later
explanation was wrongly blocked by the observe-before-explain gate. The
governor phase and the learner model must move together.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from packetlab.lab import curriculum as curriculum_mod
from packetlab.lab.cli import sync_observation
from packetlab.lab.governor import Action, Governor
from packetlab.lab.learner import LearnerModel
from packetlab.lab.trace import Trace, new_run_id


class ObservationSync(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.run_id = new_run_id()
        self.gov = Governor(curriculum_mod.load(),
                            trace=Trace(self.run_id, "v3.0", base_dir=self.tmp),
                            state_path=self.tmp / "lesson.json")
        self.learner = LearnerModel(self.tmp / "learner.json")
        self.gov.start_lesson("v3.0", self.run_id)
        self.concept = "dns.udp-53"

    def tearDown(self):
        self._tmp.cleanup()

    def _predict(self):
        action = Action("record", concept_id=self.concept, phase="predicted")
        self.gov.commit(action)
        self.learner.add_evidence(self.concept, "prediction", "p", "v3.0", self.run_id)

    def test_observation_advances_governor_and_learner_together(self):
        self._predict()
        result = sync_observation(self.gov, self.learner, self.concept, "saw it",
                                  "v3.0", self.run_id, run_ok=True)
        self.assertTrue(result["recorded"])
        # Governor phase advanced...
        self.assertEqual(self.gov.status()["concept_phase"][self.concept], "observed")
        # ...and the learner recorded the observation...
        kinds = [e["kind"] for e in self.learner.concept(self.concept).evidence]
        self.assertIn("observation", kinds)
        # ...so a later explanation is NOT blocked (the bug this replaced).
        explain = Action("record", concept_id=self.concept, phase="explained")
        self.assertTrue(self.gov.evaluate(explain).allowed)

    def test_observation_blocked_when_no_prediction_records_nothing(self):
        # No prediction/skip yet -> governor blocks -> learner must NOT record,
        # so the two never diverge in the other direction either.
        result = sync_observation(self.gov, self.learner, self.concept, "saw it",
                                  "v3.0", self.run_id, run_ok=True)
        self.assertFalse(result["recorded"])
        self.assertIn("governor blocked", result["reason"])
        self.assertEqual(self.learner.concept(self.concept).state, "unseen")

    def test_failed_command_records_no_observation(self):
        self._predict()
        result = sync_observation(self.gov, self.learner, self.concept, "x",
                                  "v3.0", self.run_id, run_ok=False)
        self.assertFalse(result["recorded"])
        self.assertEqual(self.gov.status()["concept_phase"][self.concept], "predicted")

    def test_no_concept_is_a_noop(self):
        result = sync_observation(self.gov, self.learner, None, "x", "v3.0",
                                  self.run_id, run_ok=True)
        self.assertFalse(result["requested"])
        self.assertFalse(result["recorded"])


class ExperimentValidateCommand(unittest.TestCase):
    """The `experiment validate` command validates the spec AND cross-checks
    every step's argv against the command policy (so a plan is reviewed before
    any command runs). This is the real consumer of ExperimentSpec."""

    def _validate(self, spec_path: str) -> int:
        import argparse
        from packetlab.lab.cli import cmd_experiment
        with contextlib.redirect_stdout(io.StringIO()):
            return cmd_experiment(argparse.Namespace(action="validate",
                                                     spec=spec_path))

    def _run(self, spec: dict) -> int:
        import json
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "exp.json"
            path.write_text(json.dumps(spec))
            return self._validate(str(path))

    def test_committed_example_validates(self):
        example = (Path(__file__).resolve().parents[1] / "docs" / "examples"
                   / "experiment-dns-cache.json")
        self.assertEqual(self._validate(str(example)), 0)

    def test_bad_category_step_fails_policy(self):
        spec = {
            "id": "bad-exp", "lesson_id": "v3.0", "objective": "x",
            "prediction_prompt": "p",
            "steps": [{"description": "rm", "category": "observe_network",
                       "argv": ["rm", "-rf", "/"]}],
            "expected_observations": ["nothing good"], "safety_class": "observe_only",
            "reflection_prompt": "r", "mastery_evidence": ["dns.udp-53"]}
        self.assertEqual(self._run(spec), 1)  # step fails policy -> non-zero


if __name__ == "__main__":
    unittest.main()
