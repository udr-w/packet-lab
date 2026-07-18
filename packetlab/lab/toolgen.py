"""Generated-tool lifecycle: lookup, validate, test, register, invoke, retire.

Generated tools are treated as untrusted software from creation to retirement:

1. lookup()   — deterministic registry search runs FIRST; a tool is generated
                only when no adequate one exists (reuse before generation).
2. validate() — parse the EXACT bytes that will execute (rejecting encoding
                tricks), run the AST allow-list, check declared capabilities
                against policy, and validate the test file too. Records a
                sha256 of the validated bytes.
3. run_tests()— copy into a fresh temp dir, re-verify the sha256 matches what
                was validated (TOCTOU guard), run unittest under the restricted
                runner. A failing or unvalidated test blocks registration.
4. register() — writes tools/registry.json + a full provenance record.
5. invoke()   — validate typed inputs (path inputs must pass policy read
                checks), re-verify sha256, run under the runner, parse stdout
                JSON defensively, validate outputs against the declared schema.
                Any failure returns a structured failure, never partial data.
6. cleanup()  — retire lesson-scoped tools; quarantine unsafe ones.

Provenance (spec, capabilities requested vs approved, validation findings,
test results, execution history, checksum, retention, status) is the record a
reviewer reads to answer "why did this tool exist and what did it do?".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from packetlab.lab import astcheck
from packetlab.lab.policy import Decision, check_capabilities, check_path_input
from packetlab.lab.runner import ExecutionResult, run_restricted
from packetlab.lab.specs import (ToolSpec, ValidationResult,
                                 validate_against_schema)
from packetlab.lab.statefile import atomic_write_json, load_json, update_json
from packetlab.lab.trace import Trace

MAX_TOOL_SOURCE_BYTES = 200_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tools_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "tools"


def registry_path(root: Path | None = None) -> Path:
    return tools_dir(root) / "registry.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ToolArtifacts:
    """The four files that make up a generated tool on disk."""

    tool_id: str
    directory: Path
    spec: ToolSpec
    source: bytes
    test_source: bytes


# ---- lookup (reuse before generation) ------------------------------------

def lookup(purpose_keywords: list[str], root: Path | None = None) -> list[dict]:
    """Deterministic registry search. Returns matching registered tools."""
    registry = load_json(registry_path(root), default={"tools": []})
    needles = [k.lower() for k in purpose_keywords if k]
    matches = []
    for entry in registry.get("tools", []):
        if entry.get("status") == "quarantined":
            continue
        haystack = (entry.get("purpose", "") + " " + " ".join(entry.get("tags", []))
                    + " " + entry.get("tool_id", "")).lower()
        score = sum(1 for n in needles if n in haystack)
        if score:
            matches.append({**entry, "_score": score})
    return sorted(matches, key=lambda e: e["_score"], reverse=True)


# ---- validation ----------------------------------------------------------

def validate(spec: ToolSpec, source: bytes, test_source: bytes,
             workspace: Path, permitted_categories: list[str]) -> dict:
    """Full pre-execution validation. Returns a structured findings record."""
    findings: dict = {"ok": False, "checks": {}, "source_sha256": None}

    if len(source) > MAX_TOOL_SOURCE_BYTES or len(test_source) > MAX_TOOL_SOURCE_BYTES:
        findings["checks"]["size"] = ["tool or test source exceeds the size cap"]
        return findings
    findings["checks"]["size"] = []

    enc = astcheck.reject_encoding_tricks(source) + astcheck.reject_encoding_tricks(test_source)
    findings["checks"]["encoding"] = enc

    cap = check_capabilities(spec, permitted_categories, workspace)
    findings["checks"]["capabilities"] = [] if cap.allowed else [cap.reason]

    src_result = astcheck.validate_source(source.decode("utf-8", "replace"), spec)
    findings["checks"]["source_ast"] = src_result.errors
    test_result = astcheck.validate_source(test_source.decode("utf-8", "replace"),
                                           spec, is_test=True)
    findings["checks"]["test_ast"] = test_result.errors

    findings["source_sha256"] = _sha256(source)
    findings["test_sha256"] = _sha256(test_source)
    findings["ok"] = all(not v for v in findings["checks"].values())
    return findings


# ---- test execution ------------------------------------------------------

def run_tests(artifacts: ToolArtifacts, expected_source_sha: str,
              expected_test_sha: str, workspace: Path) -> ExecutionResult:
    """Run the tool's unit tests in a fresh temp copy, after a TOCTOU re-check."""
    if _sha256(artifacts.source) != expected_source_sha:
        return ExecutionResult("refused", None, "", "", 0,
                               detail="tool source changed since validation")
    if _sha256(artifacts.test_source) != expected_test_sha:
        return ExecutionResult("refused", None, "", "", 0,
                               detail="test source changed since validation")
    sandbox = workspace / f".test-{artifacts.tool_id}"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    try:
        (sandbox / "tool.py").write_bytes(artifacts.source)
        (sandbox / "test_tool.py").write_bytes(artifacts.test_source)
        return run_restricted(
            ["python3", "-m", "unittest", "test_tool", "-v"],
            cwd=sandbox, timeout_s=artifacts.spec.timeout_seconds + 10,
            max_output_bytes=200_000, limit_processes=True)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ---- registration & provenance ------------------------------------------

def register(artifacts: ToolArtifacts, validation: dict, test_result: ExecutionResult,
             generator: str, root: Path | None = None,
             trace: Trace | None = None) -> dict:
    """Persist the tool and its provenance. Refuses if validation/tests failed."""
    if not validation.get("ok"):
        raise ValueError("cannot register a tool that failed validation")
    if test_result.status != "ok":
        raise ValueError(f"cannot register a tool whose tests did not pass "
                         f"({test_result.status})")

    target = tools_dir(root) / "generated" / artifacts.tool_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "tool.py").write_bytes(artifacts.source)
    (target / "test_tool.py").write_bytes(artifacts.test_source)
    atomic_write_json(target / "spec.json", artifacts.spec.to_dict())

    provenance = {
        "tool_id": artifacts.tool_id,
        "version": artifacts.spec.version,
        "lesson_id": artifacts.spec.lesson_id,
        "created_at": _now(),
        "generator": generator,
        "source_sha256": validation["source_sha256"],
        "test_sha256": validation["test_sha256"],
        "requested_capabilities": {
            "commands": artifacts.spec.capability_commands,
            "filesystem": {"read": artifacts.spec.capability_fs_read,
                           "write": artifacts.spec.capability_fs_write},
            "network": artifacts.spec.capability_network,
        },
        "approved_capabilities": {
            "commands": [], "filesystem": {"read": artifacts.spec.capability_fs_read,
                                           "write": artifacts.spec.capability_fs_write},
            "network": "none",
        },
        "dependencies": artifacts.spec.dependencies,
        "validation": validation,
        "test_results": test_result.to_summary(),
        "executions": [],
        "retention": artifacts.spec.retention,
        "status": "registered",
    }
    atomic_write_json(target / "provenance.json", provenance)
    _upsert_registry(artifacts, root)
    if trace is not None:
        trace.emit("toolgen", "tool_registered", tool_id=artifacts.tool_id,
                   generator=generator, source_sha256=validation["source_sha256"])
    return provenance


def _upsert_registry(artifacts: ToolArtifacts, root: Path | None) -> None:
    entry = {
        "tool_id": artifacts.tool_id,
        "path": str(Path("tools") / "generated" / artifacts.tool_id),
        "purpose": artifacts.spec.purpose,
        "tags": _tags(artifacts.spec),
        "status": "registered",
        "retention": artifacts.spec.retention,
        "lesson_id": artifacts.spec.lesson_id,
    }

    def mutate(data: dict) -> dict:
        tools = data.setdefault("tools", [])
        tools[:] = [t for t in tools if t.get("tool_id") != artifacts.tool_id]
        tools.append(entry)
        return data

    update_json(registry_path(root), mutate,
                default={"tools": [], "generation": 0})


def _tags(spec: ToolSpec) -> list[str]:
    words = spec.purpose.lower().replace("/", " ").split()
    stop = {"the", "a", "an", "of", "and", "to", "from", "for", "in", "on"}
    return sorted({w.strip(".,") for w in words if w not in stop and len(w) > 2})


# ---- invocation ----------------------------------------------------------

def invoke(tool_id: str, inputs: dict, workspace: Path, root: Path | None = None,
           trace: Trace | None = None) -> dict:
    """Invoke a registered tool with typed inputs. Always structured result."""
    directory = tools_dir(root) / "generated" / tool_id
    prov_path = directory / "provenance.json"
    if not prov_path.exists():
        return _failure(tool_id, "not_registered", "tool is not registered")
    provenance = load_json(prov_path)
    if provenance.get("status") == "quarantined":
        return _failure(tool_id, "quarantined", "tool is quarantined")

    spec, spec_result = ToolSpec.from_dict(load_json(directory / "spec.json"))
    if spec is None:
        return _failure(tool_id, "bad_spec", "; ".join(spec_result.errors))

    source = (directory / "tool.py").read_bytes()
    if _sha256(source) != provenance.get("source_sha256"):
        return _failure(tool_id, "checksum_mismatch",
                        "on-disk source does not match the validated checksum")

    input_result = validate_against_schema(inputs, spec.inputs, "inputs")
    if not input_result.ok:
        return _failure(tool_id, "bad_inputs", "; ".join(input_result.errors))
    for name, field_schema in spec.inputs.items():
        if field_schema["type"] == "path":
            decision = check_path_input(inputs[name], spec, workspace)
            if not decision.allowed:
                return _failure(tool_id, "bad_input_path", decision.reason)

    result = run_restricted(["python3", str(directory / "tool.py")],
                            cwd=workspace, timeout_s=spec.timeout_seconds,
                            max_output_bytes=spec.max_output_bytes,
                            stdin_data=json.dumps(inputs), limit_processes=True)
    record = {"tool_id": tool_id, "status": None, "run": result.to_summary()}

    if result.status != "ok":
        record.update(status="execution_failed", reason=result.detail,
                      stderr=result.stderr[:500])
    else:
        parsed = _safe_parse(result.stdout)
        if parsed is None:
            record.update(status="bad_output", reason="tool stdout was not valid JSON")
        else:
            out_result = validate_against_schema(parsed, spec.outputs, "outputs")
            if not out_result.ok:
                record.update(status="schema_violation",
                              reason="; ".join(out_result.errors))
            else:
                record.update(status="ok", outputs=parsed)

    _append_execution(directory, tool_id, record, trace)
    if trace is not None:
        trace.emit("toolgen", "tool_invoked", tool_id=tool_id,
                   status=record["status"], run=result.to_summary())
    return record


def _safe_parse(text: str):
    if len(text) > MAX_TOOL_SOURCE_BYTES * 2:
        return None
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except Exception:
        return None


def _reject_constant(value):
    raise ValueError("forbidden JSON constant")


def _append_execution(directory: Path, tool_id: str, record: dict,
                      trace: Trace | None) -> None:
    prov_path = directory / "provenance.json"

    def mutate(data: dict) -> dict:
        data.setdefault("executions", []).append({
            "ts": _now(),
            "run_id": trace.run_id if trace else None,
            "status": record["status"],
            "duration_ms": record["run"]["duration_ms"],
        })
        return data

    update_json(prov_path, mutate)


def _failure(tool_id: str, status: str, reason: str) -> dict:
    return {"tool_id": tool_id, "status": status, "reason": reason}


# ---- retention & cleanup -------------------------------------------------

def quarantine(tool_id: str, reason: str, root: Path | None = None,
               trace: Trace | None = None) -> dict:
    directory = tools_dir(root) / "generated" / tool_id
    if (directory / "provenance.json").exists():
        def mutate(data: dict) -> dict:
            data["status"] = "quarantined"
            data["quarantine_reason"] = reason
            return data
        update_json(directory / "provenance.json", mutate)

    def reg_mutate(data: dict) -> dict:
        for entry in data.get("tools", []):
            if entry.get("tool_id") == tool_id:
                entry["status"] = "quarantined"
        return data

    update_json(registry_path(root), reg_mutate, default={"tools": [], "generation": 0})
    if trace is not None:
        trace.emit("toolgen", "tool_quarantined", tool_id=tool_id, reason=reason)
    return {"tool_id": tool_id, "status": "quarantined", "reason": reason}


def cleanup(lesson_id: str, root: Path | None = None,
            trace: Trace | None = None) -> list[str]:
    """Remove lesson-scoped tools whose lesson has ended. Returns removed ids."""
    registry = load_json(registry_path(root), default={"tools": []})
    removed = []
    for entry in list(registry.get("tools", [])):
        if entry.get("lesson_id") == lesson_id and entry.get("retention") == "lesson":
            directory = tools_dir(root) / "generated" / entry["tool_id"]
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(entry["tool_id"])

    if removed:
        def mutate(data: dict) -> dict:
            data["tools"] = [t for t in data.get("tools", [])
                             if t.get("tool_id") not in removed]
            return data
        update_json(registry_path(root), mutate, default={"tools": [], "generation": 0})
        if trace is not None:
            trace.emit("toolgen", "tools_cleaned_up", lesson_id=lesson_id, removed=removed)
    return removed
