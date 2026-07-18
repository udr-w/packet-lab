"""AST validator — the load-bearing gate against dangerous generated code."""

import unittest

from packetlab.lab.astcheck import reject_encoding_tricks, validate_source
from packetlab.lab.specs import ToolSpec


def _spec(write=()):
    spec, _ = ToolSpec.from_dict({
        "id": "t", "purpose": "p", "lesson_id": "v1.1",
        "inputs": {"x": {"type": "string"}}, "outputs": {"y": {"type": "integer"}},
        "capabilities": {"commands": [], "filesystem": {"read": [], "write": list(write)},
                         "network": "none"},
        "limits": {"timeout_seconds": 5, "max_output_bytes": 1000},
        "dependencies": {"python": ["standard-library-only"]}, "retention": "lesson"})
    return spec


CLEAN = "import json, sys\nd = json.load(sys.stdin)\nprint(json.dumps({'y': len(d['x'])}))"


class AstRejections(unittest.TestCase):
    REJECTED = {
        "os import": "import os",
        "subprocess from": "from subprocess import run",
        "socket": "import socket",
        "threading": "import threading",
        "multiprocessing": "import multiprocessing",
        "ctypes": "import ctypes",
        "importlib": "import importlib",
        "pathlib": "import pathlib",  # would bypass open() gate
        "resource": "import resource",
        "eval": "eval('1+1')",
        "exec": "exec('x=1')",
        "compile": "compile('x', 'f', 'exec')",
        "__import__": "__import__('os')",
        "getattr computed": "getattr(x, '__globa' + 'ls__')",
        "setattr": "setattr(x, 'a', 1)",
        "globals": "globals()",
        "vars": "vars()",
        "breakpoint": "breakpoint()",
        "input": "input()",
        "dunder globals": "f.__globals__",
        "dunder subclasses": "().__class__.__bases__[0].__subclasses__()",
        "str.format reflection": "'{0.__class__}'.format(())",
        "open read /etc": "open('/etc/passwd').read()",
        "open write no cap": "open('x', 'w').write('y')",
        "open traversal": "open('../../etc/passwd').read()",
    }

    def test_rejections(self):
        spec = _spec()
        for name, src in self.REJECTED.items():
            with self.subTest(case=name):
                self.assertFalse(validate_source(src, spec).ok,
                                 f"{name} should be rejected")

    def test_clean_source_accepted(self):
        self.assertTrue(validate_source(CLEAN, _spec()).ok)

    def test_open_write_allowed_with_capability(self):
        spec = _spec(write=["out.txt"])
        self.assertTrue(validate_source("open('out.txt', 'w').write('y')", spec).ok)

    def test_dunder_inside_lambda_caught(self):
        # ast.walk must reach nested scopes, not just the top level.
        src = "f = lambda o: o.__class__\n"
        self.assertFalse(validate_source(src, _spec()).ok)

    def test_test_file_may_import_unittest_and_tool(self):
        spec = _spec()
        src = ("import unittest\nimport tool\n"
               "class T(unittest.TestCase):\n"
               "    def test(self): self.assertIsNotNone(tool)\n")
        self.assertTrue(validate_source(src, spec, is_test=True).ok)
        # unittest/tool are only allowed in a test file, not a tool.
        self.assertFalse(validate_source(src, spec, is_test=False).ok)

    def test_lazy_test_that_never_exercises_tool_rejected(self):
        spec = _spec()
        lazy = ("import unittest\nimport tool\n"
                "class T(unittest.TestCase):\n"
                "    def test(self): self.assertTrue(True)\n")
        self.assertFalse(validate_source(lazy, spec, is_test=True).ok)
        no_import = ("import unittest\n"
                     "class T(unittest.TestCase):\n"
                     "    def test(self): self.assertTrue(True)\n")
        self.assertFalse(validate_source(no_import, spec, is_test=True).ok)


class EncodingTricks(unittest.TestCase):
    def test_utf8_clean(self):
        self.assertEqual(reject_encoding_tricks(b"print(1)"), [])

    def test_bom_rejected(self):
        self.assertTrue(reject_encoding_tricks(b"\xef\xbb\xbfprint(1)"))

    def test_non_utf8_cookie_rejected(self):
        self.assertTrue(reject_encoding_tricks(b"# -*- coding: rot13 -*-\ncevag(1)"))

    def test_invalid_utf8_rejected(self):
        self.assertTrue(reject_encoding_tricks(b"x = '\xff\xfe'"))


if __name__ == "__main__":
    unittest.main()
