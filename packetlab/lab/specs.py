"""Structured tool and experiment specifications.

Every generated tool and every experiment is described by a typed spec that
is validated deterministically before anything runs. Validation is strict:
unknown keys are errors, so an agent cannot smuggle fields past review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re


TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
LESSON_ID_PATTERN = re.compile(r"^v\d+\.\d+$")
CONCEPT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*([.-][a-z0-9]+)*$")

VALUE_TYPES = ("string", "integer", "number", "boolean", "path")
ACCESS_MODES = ("read",)  # path inputs are read-only; tools never take write paths
NETWORK_MODES = ("none",)  # generated tools get no network access, full stop
RETENTION_MODES = ("lesson", "archive", "keep")
SAFETY_CLASSES = ("observe_only", "local_traffic", "modifies_cache")
DEPENDENCY_MODES = ("standard-library-only",)

MAX_TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 1_000_000


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    @staticmethod
    def failure(errors: list[str]) -> "ValidationResult":
        return ValidationResult(ok=False, errors=errors)

    @staticmethod
    def success() -> "ValidationResult":
        return ValidationResult(ok=True, errors=[])


class _Checker:
    """Collects errors while walking a spec dict. Strict about unknown keys."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def require_keys(self, data: dict, required: tuple, optional: tuple, where: str) -> bool:
        if not isinstance(data, dict):
            self.error(f"{where}: expected an object, got {type(data).__name__}")
            return False
        for key in required:
            if key not in data:
                self.error(f"{where}: missing required key '{key}'")
        allowed = set(required) | set(optional)
        for key in data:
            if key not in allowed:
                self.error(f"{where}: unknown key '{key}' (unknown keys are rejected)")
        return all(key in data for key in required)

    def string(self, value, where: str, pattern: re.Pattern | None = None,
               max_len: int = 500) -> str | None:
        if not isinstance(value, str) or not value.strip():
            self.error(f"{where}: expected a non-empty string")
            return None
        if len(value) > max_len:
            self.error(f"{where}: longer than {max_len} characters")
            return None
        if pattern is not None and not pattern.match(value):
            self.error(f"{where}: '{value}' does not match required format {pattern.pattern}")
            return None
        return value

    def string_list(self, value, where: str, max_items: int = 50) -> list[str]:
        if not isinstance(value, list):
            self.error(f"{where}: expected a list of strings")
            return []
        if len(value) > max_items:
            self.error(f"{where}: more than {max_items} items")
            return []
        out = []
        for i, item in enumerate(value):
            checked = self.string(item, f"{where}[{i}]")
            if checked is not None:
                out.append(checked)
        return out

    def choice(self, value, where: str, choices: tuple) -> str | None:
        if value not in choices:
            self.error(f"{where}: '{value}' is not one of {list(choices)}")
            return None
        return value

    def bounded_int(self, value, where: str, low: int, high: int) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            self.error(f"{where}: expected an integer")
            return None
        if not (low <= value <= high):
            self.error(f"{where}: {value} outside allowed range [{low}, {high}]")
            return None
        return value


def _check_field_schema(checker: _Checker, data, where: str,
                        allow_access: bool) -> dict:
    """Validate an inputs/outputs field map: {name: {type: ..., access?: ...}}."""
    result: dict = {}
    if not isinstance(data, dict):
        checker.error(f"{where}: expected an object of named fields")
        return result
    if len(data) > 20:
        checker.error(f"{where}: more than 20 fields")
        return result
    for name, schema in data.items():
        field_where = f"{where}.{name}"
        if not isinstance(name, str) or not CONCEPT_ID_PATTERN.match(name.replace("_", "-")):
            checker.error(f"{field_where}: field names must be lower-case identifiers")
            continue
        optional = ("access",) if allow_access else ()
        if not checker.require_keys(schema, ("type",), optional, field_where):
            continue
        value_type = checker.choice(schema["type"], f"{field_where}.type", VALUE_TYPES)
        entry = {"type": value_type}
        if "access" in schema:
            if schema.get("type") != "path":
                checker.error(f"{field_where}: 'access' is only valid for path fields")
            entry["access"] = checker.choice(schema["access"], f"{field_where}.access",
                                             ACCESS_MODES)
        elif allow_access and schema.get("type") == "path":
            checker.error(f"{field_where}: path inputs must declare access: read")
        result[name] = entry
    return result


@dataclass(frozen=True)
class ToolSpec:
    """A generated tool's contract: what it does, takes, returns, and may touch."""

    id: str
    version: int
    purpose: str
    lesson_id: str
    inputs: dict
    outputs: dict
    capability_commands: list[str]
    capability_fs_read: list[str]
    capability_fs_write: list[str]
    capability_network: str
    timeout_seconds: int
    max_output_bytes: int
    dependencies: list[str]
    retention: str

    @staticmethod
    def from_dict(data) -> tuple["ToolSpec | None", ValidationResult]:
        checker = _Checker()
        required = ("id", "purpose", "lesson_id", "inputs", "outputs",
                    "capabilities", "limits", "dependencies", "retention")
        optional = ("version",)
        if not checker.require_keys(data, required, optional, "tool spec"):
            return None, ValidationResult.failure(checker.errors)

        tool_id = checker.string(data["id"], "id", TOOL_ID_PATTERN, max_len=64)
        version = data.get("version", 1)
        version = checker.bounded_int(version, "version", 1, 10_000)
        purpose = checker.string(data["purpose"], "purpose")
        lesson_id = checker.string(data["lesson_id"], "lesson_id", LESSON_ID_PATTERN)
        inputs = _check_field_schema(checker, data["inputs"], "inputs", allow_access=True)
        outputs = _check_field_schema(checker, data["outputs"], "outputs", allow_access=False)
        if not outputs and isinstance(data["outputs"], dict) and not data["outputs"]:
            checker.error("outputs: a tool must declare at least one output")

        caps = data["capabilities"]
        commands: list[str] = []
        fs_read: list[str] = []
        fs_write: list[str] = []
        network = None
        if checker.require_keys(caps, ("commands", "filesystem", "network"), (), "capabilities"):
            commands = checker.string_list(caps["commands"], "capabilities.commands")
            network = checker.choice(caps["network"], "capabilities.network", NETWORK_MODES)
            fs = caps["filesystem"]
            if checker.require_keys(fs, ("read", "write"), (), "capabilities.filesystem"):
                fs_read = checker.string_list(fs["read"], "capabilities.filesystem.read")
                fs_write = checker.string_list(fs["write"], "capabilities.filesystem.write")

        timeout = None
        max_bytes = None
        limits = data["limits"]
        if checker.require_keys(limits, ("timeout_seconds", "max_output_bytes"), (), "limits"):
            timeout = checker.bounded_int(limits["timeout_seconds"], "limits.timeout_seconds",
                                          1, MAX_TIMEOUT_SECONDS)
            max_bytes = checker.bounded_int(limits["max_output_bytes"],
                                            "limits.max_output_bytes", 1, MAX_OUTPUT_BYTES)

        dependencies: list[str] = []
        deps = data["dependencies"]
        if checker.require_keys(deps, ("python",), (), "dependencies"):
            dependencies = checker.string_list(deps["python"], "dependencies.python")
            for dep in dependencies:
                if dep not in DEPENDENCY_MODES:
                    checker.error(
                        f"dependencies.python: '{dep}' is not allowed "
                        f"(only {list(DEPENDENCY_MODES)}; third-party packages are rejected)")

        retention = checker.choice(data["retention"], "retention", RETENTION_MODES)

        if checker.errors:
            return None, ValidationResult.failure(checker.errors)
        return ToolSpec(
            id=tool_id, version=version, purpose=purpose, lesson_id=lesson_id,
            inputs=inputs, outputs=outputs,
            capability_commands=commands, capability_fs_read=fs_read,
            capability_fs_write=fs_write, capability_network=network,
            timeout_seconds=timeout, max_output_bytes=max_bytes,
            dependencies=dependencies, retention=retention,
        ), ValidationResult.success()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "version": self.version, "purpose": self.purpose,
            "lesson_id": self.lesson_id, "inputs": self.inputs, "outputs": self.outputs,
            "capabilities": {
                "commands": self.capability_commands,
                "filesystem": {"read": self.capability_fs_read,
                               "write": self.capability_fs_write},
                "network": self.capability_network,
            },
            "limits": {"timeout_seconds": self.timeout_seconds,
                       "max_output_bytes": self.max_output_bytes},
            "dependencies": {"python": self.dependencies},
            "retention": self.retention,
        }


def validate_value(value, value_type: str) -> bool:
    """Does a runtime value match a declared spec type?"""
    if value_type == "string" or value_type == "path":
        return isinstance(value, str)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    return False


def validate_against_schema(values: dict, schema: dict, where: str) -> ValidationResult:
    """Validate runtime inputs/outputs against a spec field map. Strict."""
    errors = []
    if not isinstance(values, dict):
        return ValidationResult.failure([f"{where}: expected an object"])
    for name in values:
        if name not in schema:
            errors.append(f"{where}: undeclared field '{name}'")
    for name, field_schema in schema.items():
        if name not in values:
            errors.append(f"{where}: missing declared field '{name}'")
        elif not validate_value(values[name], field_schema["type"]):
            errors.append(f"{where}.{name}: value does not match declared type "
                          f"'{field_schema['type']}'")
    return ValidationResult(ok=not errors, errors=errors)


@dataclass(frozen=True)
class ExperimentStep:
    description: str
    category: str
    argv: list[str]


@dataclass(frozen=True)
class ExperimentSpec:
    """A structured experiment: the educational reasoning, separated from execution."""

    id: str
    lesson_id: str
    objective: str
    prediction_prompt: str
    preconditions: list[str]
    steps: list[ExperimentStep]
    expected_observations: list[str]
    data_to_collect: list[str]
    safety_class: str
    cleanup: list[ExperimentStep]
    reflection_prompt: str
    mastery_evidence: list[str]

    @staticmethod
    def from_dict(data) -> tuple["ExperimentSpec | None", ValidationResult]:
        checker = _Checker()
        required = ("id", "lesson_id", "objective", "prediction_prompt", "steps",
                    "expected_observations", "safety_class", "reflection_prompt",
                    "mastery_evidence")
        optional = ("preconditions", "data_to_collect", "cleanup")
        if not checker.require_keys(data, required, optional, "experiment spec"):
            return None, ValidationResult.failure(checker.errors)

        exp_id = checker.string(data["id"], "id", TOOL_ID_PATTERN, max_len=64)
        lesson_id = checker.string(data["lesson_id"], "lesson_id", LESSON_ID_PATTERN)
        objective = checker.string(data["objective"], "objective")
        prediction = checker.string(data["prediction_prompt"], "prediction_prompt")
        reflection = checker.string(data["reflection_prompt"], "reflection_prompt")
        safety = checker.choice(data["safety_class"], "safety_class", SAFETY_CLASSES)
        preconditions = checker.string_list(data.get("preconditions", []), "preconditions")
        observations = checker.string_list(data["expected_observations"],
                                           "expected_observations")
        collect = checker.string_list(data.get("data_to_collect", []), "data_to_collect")
        mastery = checker.string_list(data["mastery_evidence"], "mastery_evidence")
        for i, concept in enumerate(mastery):
            if not CONCEPT_ID_PATTERN.match(concept):
                checker.error(f"mastery_evidence[{i}]: '{concept}' is not a concept id")

        steps = _check_steps(checker, data["steps"], "steps")
        if not steps and not checker.errors:
            checker.error("steps: an experiment needs at least one step")
        cleanup = _check_steps(checker, data.get("cleanup", []), "cleanup")

        if checker.errors:
            return None, ValidationResult.failure(checker.errors)
        return ExperimentSpec(
            id=exp_id, lesson_id=lesson_id, objective=objective,
            prediction_prompt=prediction, preconditions=preconditions, steps=steps,
            expected_observations=observations, data_to_collect=collect,
            safety_class=safety, cleanup=cleanup, reflection_prompt=reflection,
            mastery_evidence=mastery,
        ), ValidationResult.success()


def _check_steps(checker: _Checker, data, where: str) -> list[ExperimentStep]:
    steps: list[ExperimentStep] = []
    if not isinstance(data, list):
        checker.error(f"{where}: expected a list of steps")
        return steps
    if len(data) > 20:
        checker.error(f"{where}: more than 20 steps")
        return steps
    for i, raw in enumerate(data):
        step_where = f"{where}[{i}]"
        if not checker.require_keys(raw, ("description", "category", "argv"), (), step_where):
            continue
        description = checker.string(raw["description"], f"{step_where}.description")
        category = checker.string(raw["category"], f"{step_where}.category", max_len=64)
        argv = checker.string_list(raw["argv"], f"{step_where}.argv")
        if not argv:
            checker.error(f"{step_where}.argv: a step needs a non-empty argv")
            continue
        if description and category:
            steps.append(ExperimentStep(description=description, category=category,
                                        argv=argv))
    return steps
