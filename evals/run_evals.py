"""Control-plane conformance evals.

These are NOT model-quality evals. They exercise the deterministic enforcement
points — policy, governor, AST validator, runner, untrusted wrapper — against
data fixtures and assert the decision each one makes. They evaluate the control
plane that bounds the agent, not the agent's prose. See
docs/evaluation-strategy.md for why that distinction matters and what is
therefore out of scope here (real tutoring judgement, injection *resistance*).

Every fixture is a JSON object with a common envelope:

    {
      "eval_id": "...", "category": "...", "description": "...",
      "target": "policy.check_command" | "governor.evaluate"
              | "toolgen.validate" | "runner.run_restricted"
              | "untrusted.render",
      "input": { ... target-specific ... },
      "expect": { "allowed": bool?, "status": str?, "ok": bool?,
                  "errors_contain": [str]?, "output_contains": [str]?,
                  "not_contains": [str]? }
    }

run_evals.py is one generic dispatcher over `target`, so a new eval is a data
file, not code. Exit code is non-zero if any eval fails.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from packetlab.lab import curriculum as curriculum_mod
from packetlab.lab import toolgen, untrusted
from packetlab.lab.governor import Action, Governor
from packetlab.lab.policy import check_command
from packetlab.lab.runner import run_restricted
from packetlab.lab.specs import ToolSpec
from packetlab.lab.trace import Trace, new_run_id

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _target_policy_check_command(inp: dict) -> dict:
    with tempfile.TemporaryDirectory() as ws:
        decision = check_command(inp["argv"], inp["category"], Path(ws))
    return {"allowed": decision.allowed, "reason": decision.reason,
            "rule": decision.rule}


def _target_governor_evaluate(inp: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        run_id = new_run_id()
        gov = Governor(curriculum_mod.load(),
                       trace=Trace(run_id, inp["lesson_id"], base_dir=tmp_path,
                                   learner_id="eval-learner"),
                       state_path=tmp_path / "lesson.json")
        gov.start_lesson(inp["lesson_id"], run_id)
        for prior in inp.get("commit_first", []):
            gov.commit(Action(**prior))
        decision = gov.evaluate(Action(**inp["action"]))
    return {"allowed": decision.allowed, "reason": decision.reason,
            "rule": decision.rule}


def _target_toolgen_validate(inp: dict) -> dict:
    spec, spec_result = ToolSpec.from_dict(inp["spec"])
    if spec is None:
        return {"ok": False, "errors": spec_result.errors}
    with tempfile.TemporaryDirectory() as ws:
        default_test = ("import unittest\nimport tool\n"
                        "class T(unittest.TestCase):\n"
                        "    def test(self): self.assertIsNotNone(tool)\n")
        findings = toolgen.validate(
            spec, inp["source"].encode("utf-8"),
            inp.get("test_source", default_test).encode("utf-8"),
            Path(ws), inp.get("permitted_categories", []))
    flat = [e for group in findings["checks"].values() for e in group]
    return {"ok": findings["ok"], "errors": flat}


def _target_runner(inp: dict) -> dict:
    with tempfile.TemporaryDirectory() as ws:
        result = run_restricted(inp["argv"], cwd=Path(ws),
                                timeout_s=inp.get("timeout_s", 3),
                                max_output_bytes=inp.get("max_output_bytes", 1000),
                                stdin_data=inp.get("stdin"),
                                limit_processes=inp.get("limit_processes", False))
    return {"status": result.status, "output": result.stdout,
            "stdout_truncated": result.stdout_truncated}


def _target_untrusted(inp: dict) -> dict:
    rendered = untrusted.render(inp.get("source", "x"), inp["content"])
    return {"output": rendered,
            "injection_flags": untrusted.looks_like_injection(inp["content"])}


def _target_learner_state(inp: dict) -> dict:
    """Derive a concept's mastery state from a sequence of evidence kinds."""
    from packetlab.lab.learner import LearnerModel
    concept = inp.get("concept", "c")
    with tempfile.TemporaryDirectory() as d:
        model = LearnerModel(Path(d) / "learner.json")
        for kind in inp.get("evidence", []):
            model.add_evidence(concept, kind, "x", "v3.0", None)
        return {"status": "ok", "output": model.concept(concept).state}


def _target_context_isolation(inp: dict) -> dict:
    """Build two learners and return learner A's visible context, flagging any
    leak of learner B's private evidence into it."""
    from packetlab.lab.learner import LearnerModel
    from packetlab.lab.profiles import LearnerProfiles
    concept = inp.get("concept", "dns.udp-53")
    with tempfile.TemporaryDirectory() as d:
        profiles = LearnerProfiles(Path(d))
        profiles.create("learner-a")
        profiles.create("learner-b")
        a = LearnerModel(profiles.learner_dir("learner-a") / "learner.json")
        b = LearnerModel(profiles.learner_dir("learner-b") / "learner.json")
        for kind in inp.get("a_evidence", []):
            a.add_evidence(concept, kind, "a-private", "v3.0", None)
        for kind in inp.get("b_evidence", []):
            b.add_evidence(concept, kind, "b-private-misconception", "v3.0", None)
        a_context = str([e for e in a.concept(concept).evidence])
        leaked = "b-private" in a_context
        return {"status": "leaked" if leaked else "isolated",
                "output": a_context + " state=" + a.concept(concept).state}


def _target_resume_render(inp: dict) -> dict:
    """Build a learner state from the fixture, snapshot it, render a view.

    Exercises the tutor's resume surface: the default view must be concise
    and free of operational machinery; verbose is where diagnostics live.
    """
    from packetlab.lab import resume as resume_mod
    from packetlab.lab.profiles import LearnerProfiles
    from packetlab.lab.statefile import atomic_write_json
    with tempfile.TemporaryDirectory() as d:
        state = Path(d)
        if inp.get("learner"):
            profiles = LearnerProfiles(state)
            profiles.create(inp["learner"])
            ldir = profiles.learner_dir(inp["learner"])
            if inp.get("lesson_state") is not None:
                atomic_write_json(ldir / "lesson.json", inp["lesson_state"])
            if inp.get("learner_model") is not None:
                atomic_write_json(ldir / "learner.json", inp["learner_model"])
        snapshot = resume_mod.build_snapshot(state_dir=state)
        render = resume_mod.render_verbose if inp.get("mode") == "verbose" \
            else resume_mod.render_learner
        return {"status": snapshot["status"], "output": render(snapshot)}


def _target_preflight_plan(inp: dict) -> dict:
    """Plan (and optionally message a failed) private preflight."""
    from packetlab.lab import preflight
    lesson = curriculum_mod.load().lesson(inp["lesson_id"])
    plan = preflight.plan(lesson, next_phase=inp.get("next_phase"),
                          reserved_targets=tuple(inp.get("reserved_targets",
                                                         [])))
    disposable = plan.get("disposable_hostname", "")
    contaminates = disposable and disposable in inp.get("reserved_targets", [])
    output = json.dumps(plan)
    if inp.get("simulate_failure"):
        results = {"results": [{"id": "binary:tcpdump", "ok": False,
                                "target": "/usr/bin/tcpdump"}]}
        output = preflight.learner_message_for_failure(results)
    return {"ok": not contaminates, "status": plan["outcome"],
            "output": output}


TARGETS = {
    "resume.render": _target_resume_render,
    "preflight.plan": _target_preflight_plan,
    "policy.check_command": _target_policy_check_command,
    "governor.evaluate": _target_governor_evaluate,
    "toolgen.validate": _target_toolgen_validate,
    "runner.run_restricted": _target_runner,
    "untrusted.render": _target_untrusted,
    "learner.state": _target_learner_state,
    "profiles.context_isolation": _target_context_isolation,
}


def _check_expectation(expect: dict, actual: dict) -> list[str]:
    problems = []
    for key in ("allowed", "status", "ok"):
        if key in expect and actual.get(key) != expect[key]:
            problems.append(f"{key}: expected {expect[key]!r}, got {actual.get(key)!r}")
    for needle in expect.get("errors_contain", []):
        joined = " ".join(actual.get("errors", []))
        if needle not in joined and needle not in actual.get("reason", "") \
                and needle not in actual.get("rule", ""):
            problems.append(f"errors_contain: '{needle}' not found")
    for needle in expect.get("output_contains", []):
        blob = actual.get("output", "") + " " + str(actual.get("injection_flags", ""))
        if needle not in blob:
            problems.append(f"output_contains: '{needle}' not found")
    not_contains = expect.get("not_contains", [])
    if isinstance(not_contains, str):
        not_contains = [not_contains]
    for needle in not_contains:
        if needle in actual.get("output", ""):
            problems.append(f"not_contains: '{needle}' unexpectedly present")
    return problems


def load_fixtures() -> list[dict]:
    fixtures = []
    for path in sorted(FIXTURES_DIR.rglob("*.json")):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        items = data if isinstance(data, list) else [data]
        for item in items:
            item["_file"] = str(path.relative_to(FIXTURES_DIR))
            fixtures.append(item)
    return fixtures


def main(argv: list[str] | None = None) -> int:
    del argv
    fixtures = load_fixtures()
    by_category: dict[str, list[bool]] = {}
    failures = []

    for fixture in fixtures:
        target = TARGETS.get(fixture["target"])
        category = fixture.get("category", "uncategorised")
        by_category.setdefault(category, [])
        if target is None:
            failures.append((fixture, [f"unknown target {fixture['target']}"]))
            by_category[category].append(False)
            continue
        try:
            actual = target(fixture["input"])
            problems = _check_expectation(fixture["expect"], actual)
        except Exception as exc:  # a crash is a failed eval, not a runner crash
            problems = [f"raised {type(exc).__name__}: {exc}"]
        by_category[category].append(not problems)
        if problems:
            failures.append((fixture, problems))

    print("Packet Lab — control-plane conformance evals\n")
    for category in sorted(by_category):
        results = by_category[category]
        print(f"  {category:16} {sum(results)}/{len(results)} passed")
    print()
    if failures:
        print("Failures:")
        for fixture, problems in failures:
            print(f"  [{fixture.get('eval_id')}] {fixture.get('_file')}")
            for problem in problems:
                print(f"      - {problem}")
    total = sum(len(v) for v in by_category.values())
    passed = sum(sum(v) for v in by_category.values())
    print(f"\nResult: {passed}/{total} evals passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
