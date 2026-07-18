"""Regression tests for the scripted end-to-end demo."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packetlab.lab import demo
from packetlab.lab.runner import ExecutionResult


class HappyPathResultHandling(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.gov, self.trace, self.learner, self.workspace = demo._new_env(self.tmp)
        self.gov.start_lesson("v1.1", self.trace.run_id)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _nonzero_result():
        return ExecutionResult(
            status="nonzero", exit_code=1, stdout="", stderr="ping failed",
            duration_ms=5, detail="exited with code 1")

    def test_nonzero_command_records_no_observation_explanation_or_mastery(self):
        with mock.patch.object(demo, "run_restricted",
                               return_value=self._nonzero_result()):
            with contextlib.redirect_stdout(io.StringIO()):
                result = demo._happy_path(
                    self.gov, self.trace, self.learner, self.workspace, self.tmp)

        concept = self.learner.concept("icmp.echo-request-reply")
        self.assertEqual(result, 1)
        self.assertEqual(concept.state, "in_progress")
        self.assertEqual([entry["kind"] for entry in concept.evidence],
                         ["prediction"])
        governor_state = self.gov.status()
        self.assertEqual(
            governor_state["concept_phase"]["icmp.echo-request-reply"], "predicted")
        self.assertTrue(governor_state["closed"])
        self.assertTrue(governor_state["aborted"])

    def test_nonzero_command_stops_tool_lifecycle_and_reports_failure(self):
        output = io.StringIO()
        with mock.patch.object(demo, "run_restricted",
                               return_value=self._nonzero_result()), \
                mock.patch.object(demo.toolgen, "lookup") as lookup, \
                contextlib.redirect_stdout(output):
            result = demo._happy_path(
                self.gov, self.trace, self.learner, self.workspace, self.tmp)

        self.assertEqual(result, 1)
        lookup.assert_not_called()
        self.assertIn("guarded command failed", output.getvalue())
        self.assertNotIn("Demo complete", output.getvalue())


if __name__ == "__main__":
    unittest.main()
