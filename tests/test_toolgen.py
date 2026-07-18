"""Generated-tool lifecycle — validation, testing, registration, invocation."""

import tempfile
import unittest
from pathlib import Path

from packetlab.lab import toolgen
from packetlab.lab.specs import ToolSpec
from packetlab.lab.toolgen import ToolArtifacts

SPEC = {
    "id": "adder", "version": 1, "purpose": "Add two integers from stdin json",
    "lesson_id": "v1.1", "inputs": {"a": {"type": "integer"}, "b": {"type": "integer"}},
    "outputs": {"sum": {"type": "integer"}},
    "capabilities": {"commands": [], "filesystem": {"read": [], "write": []},
                     "network": "none"},
    "limits": {"timeout_seconds": 5, "max_output_bytes": 10000},
    "dependencies": {"python": ["standard-library-only"]}, "retention": "lesson",
}
SOURCE = b"""import json
import sys


def add(a, b):
    return a + b


def main():
    d = json.load(sys.stdin)
    print(json.dumps({'sum': add(d['a'], d['b'])}))


if __name__ == '__main__':
    main()
"""
TEST = b"""import unittest
import tool
class T(unittest.TestCase):
    def test_add(self):
        self.assertEqual(tool.add(2, 3), 5)
if __name__ == '__main__':
    unittest.main()
"""
UNSAFE = b"import os\nos.system('id')\n"


class ToolLifecycle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        self.spec, _ = ToolSpec.from_dict(SPEC)

    def tearDown(self):
        self._tmp.cleanup()

    def _artifacts(self, source=SOURCE, test=TEST):
        return ToolArtifacts("adder", self.root / "tools", self.spec, source, test)

    def test_validate_clean_passes(self):
        findings = toolgen.validate(self.spec, SOURCE, TEST, self.ws, ["ping"])
        self.assertTrue(findings["ok"], findings["checks"])

    def test_validate_unsafe_source_fails(self):
        findings = toolgen.validate(self.spec, UNSAFE, TEST, self.ws, ["ping"])
        self.assertFalse(findings["ok"])
        self.assertTrue(findings["checks"]["source_ast"])

    def test_unsafe_test_file_fails(self):
        findings = toolgen.validate(self.spec, SOURCE, UNSAFE, self.ws, ["ping"])
        self.assertFalse(findings["ok"])
        self.assertTrue(findings["checks"]["test_ast"])

    def test_register_and_invoke(self):
        findings = toolgen.validate(self.spec, SOURCE, TEST, self.ws, ["ping"])
        result = toolgen.run_tests(self._artifacts(), findings["source_sha256"],
                                   findings["test_sha256"], self.ws)
        self.assertEqual(result.status, "ok")
        prov = toolgen.register(self._artifacts(), findings, result,
                                generator="fixture", root=self.root)
        self.assertEqual(prov["status"], "registered")
        invoked = toolgen.invoke("adder", {"a": 2, "b": 3}, self.ws, root=self.root)
        self.assertEqual(invoked["status"], "ok")
        self.assertEqual(invoked["outputs"], {"sum": 5})

    def test_register_refuses_failed_validation(self):
        bad = toolgen.validate(self.spec, UNSAFE, TEST, self.ws, ["ping"])
        with self.assertRaises(ValueError):
            toolgen.register(self._artifacts(UNSAFE), bad,
                             _fake_ok(), generator="fixture", root=self.root)

    def test_toctou_source_change_refused(self):
        findings = toolgen.validate(self.spec, SOURCE, TEST, self.ws, ["ping"])
        tampered = self._artifacts(source=SOURCE + b"# changed\n")
        result = toolgen.run_tests(tampered, findings["source_sha256"],
                                   findings["test_sha256"], self.ws)
        self.assertEqual(result.status, "refused")

    def test_invoke_bad_inputs_structured_failure(self):
        findings = toolgen.validate(self.spec, SOURCE, TEST, self.ws, ["ping"])
        result = toolgen.run_tests(self._artifacts(), findings["source_sha256"],
                                   findings["test_sha256"], self.ws)
        toolgen.register(self._artifacts(), findings, result, generator="fixture",
                         root=self.root)
        bad = toolgen.invoke("adder", {"a": "not-int", "b": 3}, self.ws, root=self.root)
        self.assertEqual(bad["status"], "bad_inputs")

    def test_checksum_mismatch_refuses_invoke(self):
        findings = toolgen.validate(self.spec, SOURCE, TEST, self.ws, ["ping"])
        result = toolgen.run_tests(self._artifacts(), findings["source_sha256"],
                                   findings["test_sha256"], self.ws)
        toolgen.register(self._artifacts(), findings, result, generator="fixture",
                         root=self.root)
        # Tamper the on-disk tool after registration.
        (self.root / "tools" / "generated" / "adder" / "tool.py").write_bytes(
            SOURCE + b"print('extra')\n")
        result = toolgen.invoke("adder", {"a": 1, "b": 1}, self.ws, root=self.root)
        self.assertEqual(result["status"], "checksum_mismatch")

    def test_lookup_and_cleanup(self):
        findings = toolgen.validate(self.spec, SOURCE, TEST, self.ws, ["ping"])
        result = toolgen.run_tests(self._artifacts(), findings["source_sha256"],
                                   findings["test_sha256"], self.ws)
        toolgen.register(self._artifacts(), findings, result, generator="fixture",
                         root=self.root)
        self.assertTrue(toolgen.lookup(["add"], root=self.root))
        removed = toolgen.cleanup("v1.1", root=self.root)
        self.assertIn("adder", removed)
        self.assertFalse(toolgen.lookup(["add"], root=self.root))


def _fake_ok():
    from packetlab.lab.runner import ExecutionResult
    return ExecutionResult("ok", 0, "", "", 1)


if __name__ == "__main__":
    unittest.main()
