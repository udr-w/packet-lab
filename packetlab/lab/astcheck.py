"""Static validation of generated tool source.

Generated tools are untrusted code. Before any generated source is executed,
it is parsed and walked here. The runner (rlimits + process-group kill) is the
backstop; this AST check is the primary gate that keeps dangerous code from
running at all. It is defence-in-depth layer one, and — stated plainly in
docs/threat-model.md — it is not a proof of safety.

Design stance (allow-by-exception):
- imports: only a small standard-library allow-list; everything else rejected,
  including os, subprocess, socket, shutil, ctypes, importlib, threading,
  multiprocessing, signal, resource, pty, tempfile, and pathlib (whose
  read_text/write_text/unlink/... would bypass the open() gate).
- names/calls: eval, exec, compile, __import__, globals, vars, getattr,
  setattr, delattr, breakpoint, input, help, open (gated separately), and the
  str.format / format_map reflection channel are all rejected.
- dunder attribute access (__globals__, __subclasses__, __bases__, __code__,
  __builtins__, __class__, __mro__, __dict__, ...) is rejected wherever it
  appears in the tree (ast.walk covers annotations, decorators, defaults,
  lambda and comprehension bodies — not just the top level).
- open(): the path must be a string literal and the mode a string literal;
  write/append/exclusive modes are allowed only if the spec declares a write
  capability. This is enforced for read mode too, because there is no OS-level
  filesystem confinement.

The exact bytes that will execute are what get parsed (see toolgen.validate),
so an encoding-cookie or BOM cannot make the interpreter see different source
than the validator did.
"""

from __future__ import annotations

import ast

from packetlab.lab.specs import ToolSpec, ValidationResult

ALLOWED_IMPORTS = frozenset({
    "json", "sys", "re", "math", "statistics", "collections", "dataclasses",
    "datetime", "ipaddress", "struct", "itertools", "functools", "typing",
    "argparse", "textwrap", "string", "enum", "decimal", "fractions", "bisect",
    "heapq", "unicodedata", "base64", "binascii", "hashlib",
})
# Additionally permitted only inside a generated test file: the test harness
# and the module under test itself (tools are always the single module `tool`).
TEST_EXTRA_IMPORTS = frozenset({"unittest", "tool"})

FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "vars", "locals",
    "getattr", "setattr", "delattr", "breakpoint", "input", "help",
    "memoryview", "exit", "quit", "copyright", "credits", "license",
})
# Method names whose reflective / filesystem power we refuse in generated tools.
FORBIDDEN_ATTRS = frozenset({
    "format", "format_map",  # str.format reflection channel
    "read_text", "write_text", "read_bytes", "write_bytes",  # pathlib FS bypass
    "unlink", "rmdir", "mkdir", "rename", "replace", "chmod", "symlink_to",
    "system", "popen", "spawn", "fork", "exec",
})
DUNDER_PREFIX = "__"


def _is_dunder(name: str) -> bool:
    return name.startswith(DUNDER_PREFIX) and name.endswith(DUNDER_PREFIX) \
        and len(name) > 4


def validate_source(source: str, spec: ToolSpec, *, is_test: bool = False
                    ) -> ValidationResult:
    """Walk the AST of `source`; collect every violation (no early return)."""
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ValidationResult.failure([f"source does not parse: {exc}"])

    allowed_imports = ALLOWED_IMPORTS | (TEST_EXTRA_IMPORTS if is_test else frozenset())
    can_write = bool(spec.capability_fs_write)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in allowed_imports:
                    errors.append(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top not in allowed_imports:
                errors.append(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if _is_dunder(node.attr):
                errors.append(f"access to dunder attribute '{node.attr}' is forbidden")
            elif node.attr in FORBIDDEN_ATTRS:
                errors.append(f"use of '.{node.attr}' is forbidden in generated tools")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errors.append(f"use of '{node.id}' is forbidden")
        elif isinstance(node, ast.Call):
            _check_call(node, spec, can_write, errors)

    if is_test:
        _check_test_exercises_tool(tree, errors)

    return ValidationResult(ok=not errors, errors=sorted(set(errors)))


def _check_test_exercises_tool(tree: ast.AST, errors: list[str]) -> None:
    """Best-effort: reject a generated test that never touches the tool module.

    Catches the trivial `def test(self): pass` file that passes unittest without
    exercising the tool, which would otherwise let a tool register on a vacuous
    green. This proves the test *references* the tool, not that it tests it
    meaningfully — that remains a best-effort quality gate, not a guarantee.
    """
    bound: set[str] = set()  # names that refer into the tool module
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "tool":
                    bound.add(alias.asname or "tool")
        elif isinstance(node, ast.ImportFrom) and node.module == "tool":
            for alias in node.names:
                bound.add(alias.asname or alias.name)
    if not bound:
        errors.append("test does not import the tool module")
        return
    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    if not (bound & used):
        errors.append("test imports but never exercises the tool "
                      "(no reference to the imported tool symbols)")


def _check_call(node: ast.Call, spec: ToolSpec, can_write: bool,
                errors: list[str]) -> None:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        _check_open(node, spec, can_write, errors)


def _path_declared(path: str, spec: ToolSpec) -> bool:
    """A literal open() path is acceptable if it is relative (resolves under
    the workspace at runtime) or matches a declared read/write capability."""
    import fnmatch
    if ".." in path.split("/"):
        return False
    if not path.startswith(("/", "~")):
        return True  # relative -> workspace-confined at run time
    globs = list(spec.capability_fs_read) + list(spec.capability_fs_write)
    return any(fnmatch.fnmatch(path, g) or path == g for g in globs)


def _check_open(node: ast.Call, spec: ToolSpec, can_write: bool,
                errors: list[str]) -> None:
    if not node.args:
        errors.append("open() with no arguments is forbidden")
        return
    path_arg = node.args[0]
    if not (isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str)):
        errors.append("open() path must be a string literal (no computed paths)")
    elif not _path_declared(path_arg.value, spec):
        errors.append(
            f"open() path '{path_arg.value}' is outside the workspace and not "
            "covered by a declared read/write capability")
    mode = "r"
    if len(node.args) > 1:
        mode_arg = node.args[1]
        if not (isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str)):
            errors.append("open() mode must be a string literal")
            return
        mode = mode_arg.value
    for kw in node.keywords:
        if kw.arg == "mode":
            if not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                errors.append("open() mode must be a string literal")
                return
            mode = kw.value.value
    if any(ch in mode for ch in ("w", "a", "x", "+")) and not can_write:
        errors.append("open() in a write mode requires a declared write capability")


def reject_encoding_tricks(raw: bytes) -> list[str]:
    """Reject byte-level tricks that make the interpreter decode differently.

    A UTF-8 BOM or a non-utf-8 PEP 263 coding cookie can make CPython execute
    bytes the str-level AST never saw. We insist the file is plain UTF-8.
    """
    errors: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("source has a UTF-8 BOM; plain UTF-8 without BOM is required")
    head = raw.split(b"\n")[:2]
    for line in head:
        low = line.lower()
        if b"coding" in low and (b"coding:" in low.replace(b" ", b"")
                                 or b"coding=" in low.replace(b" ", b"")):
            if b"utf-8" not in low and b"utf8" not in low:
                errors.append("only a utf-8 coding declaration is allowed")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("source is not valid UTF-8")
    return errors
