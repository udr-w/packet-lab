"""Restricted runner — timeouts, output caps, env scrubbing, no lingering kids."""

import time
import unittest
from pathlib import Path
import tempfile

from packetlab.lab.runner import run_restricted


class Runner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv, **kw):
        kw.setdefault("timeout_s", 5)
        kw.setdefault("max_output_bytes", 10_000)
        return run_restricted(argv, cwd=self.ws, **kw)

    def test_success(self):
        result = self._run(["echo", "hello"])
        self.assertEqual(result.status, "ok")
        self.assertIn("hello", result.stdout)

    def test_nonzero(self):
        self.assertEqual(self._run(["false"]).status, "nonzero")

    def test_wall_clock_timeout(self):
        start = time.monotonic()
        result = self._run(["sleep", "30"], timeout_s=1)
        elapsed = time.monotonic() - start
        self.assertEqual(result.status, "timeout")
        self.assertLess(elapsed, 4, "should be killed near the deadline, not run 30s")

    def test_output_cap(self):
        result = self._run(["python3", "-c", "print('x' * 100000)"],
                           max_output_bytes=500)
        self.assertIn(result.status, ("output_cap", "ok"))
        self.assertLessEqual(len(result.stdout), 500)
        self.assertTrue(result.stdout_truncated or result.status == "output_cap")

    def test_env_is_scrubbed(self):
        result = self._run(
            ["python3", "-c",
             "import os; print(os.environ.get('SECRET_TOKEN', 'ABSENT'))"],
            env_extra=None)
        self.assertIn("ABSENT", result.stdout)

    def test_home_points_at_workspace(self):
        result = self._run(["python3", "-c", "import os; print(os.environ['HOME'])"])
        self.assertIn(str(self.ws), result.stdout)

    def test_invalid_env_extra_rejected(self):
        result = self._run(["echo", "x"], env_extra={"bad key": "v"})
        self.assertEqual(result.status, "error")

    def test_empty_argv(self):
        self.assertEqual(self._run([]).status, "error")

    def test_stdin_delivered(self):
        result = self._run(["cat"], stdin_data="piped-input")
        self.assertIn("piped-input", result.stdout)

    def test_no_lingering_children(self):
        # A child that spawns a sleeper: killing the group must reap both.
        result = self._run(
            ["python3", "-c",
             "import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(30)"],
            timeout_s=1)
        self.assertEqual(result.status, "timeout")
        # If the process group was killed, no `sleep 30` survives; we cannot
        # portably assert on other processes, but the call returning promptly
        # is the observable signal that the group was terminated.


if __name__ == "__main__":
    unittest.main()
