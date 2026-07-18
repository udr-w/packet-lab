"""Scripted end-to-end demo of one micro-lesson.

Everything here is real except the human's answers, which are clearly labelled
RECORDED so the trace can never be mistaken for a live session:

    lesson start -> prediction recorded -> guarded `ping -c 2 127.0.0.1`
    (real execution) -> tool lookup misses -> a narrowly-scoped tool is
    proposed, statically validated, unit-tested in isolation, and registered
    -> the tool is invoked with typed inputs and its output validated against
    the declared schema -> explanation recorded -> concept reaches mastered
    -> lesson closed. `--failure` instead exercises the rejection/recovery
    paths (denied command, unsafe tool rejected and quarantined, timeout).

The demo runs entirely inside a throwaway directory, so it never touches real
lesson/learner state. On success it prints the run's trace timeline and the
hash-chain verification result.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from packetlab.lab import curriculum as curriculum_mod
from packetlab.lab import toolgen
from packetlab.lab.governor import Action, Governor
from packetlab.lab.learner import LearnerModel
from packetlab.lab.policy import check_command
from packetlab.lab.runner import run_restricted
from packetlab.lab.specs import ToolSpec
from packetlab.lab.toolgen import ToolArtifacts
from packetlab.lab.trace import Trace, new_run_id, verify_chain

RECORDED = "[RECORDED student response]"

TOOL_SPEC = {
    "id": "icmp-echo-summary",
    "version": 1,
    "purpose": "Summarise ping echo request/reply counts from ping stdout",
    "lesson_id": "v1.1",
    "inputs": {"ping_output": {"type": "string"}},
    "outputs": {"transmitted": {"type": "integer"}, "received": {"type": "integer"},
                "loss_percent": {"type": "number"}},
    "capabilities": {"commands": [], "filesystem": {"read": [], "write": []},
                     "network": "none"},
    "limits": {"timeout_seconds": 5, "max_output_bytes": 100000},
    "dependencies": {"python": ["standard-library-only"]},
    "retention": "lesson",
}

TOOL_SOURCE = b'''"""Summarise ping echo statistics. Generated tool: untrusted; runs under the restricted runner."""
import json
import re
import sys


def summarise(ping_output):
    m = re.search(r"(\\d+) packets transmitted, (\\d+) received", ping_output)
    transmitted = int(m.group(1)) if m else 0
    received = int(m.group(2)) if m else 0
    loss = 0.0 if transmitted == 0 else round(100 * (transmitted - received) / transmitted, 1)
    return {"transmitted": transmitted, "received": received, "loss_percent": loss}


def main():
    data = json.load(sys.stdin)
    print(json.dumps(summarise(data["ping_output"])))


if __name__ == "__main__":
    main()
'''

TOOL_TEST = b'''import unittest

import tool


class TestSummarise(unittest.TestCase):
    def test_all_received(self):
        out = "2 packets transmitted, 2 received, 0% packet loss"
        self.assertEqual(tool.summarise(out),
                         {"transmitted": 2, "received": 2, "loss_percent": 0.0})

    def test_partial_loss(self):
        out = "4 packets transmitted, 3 received, 25% packet loss"
        result = tool.summarise(out)
        self.assertEqual(result["received"], 3)
        self.assertEqual(result["loss_percent"], 25.0)

    def test_no_match(self):
        self.assertEqual(tool.summarise("garbage")["transmitted"], 0)


if __name__ == "__main__":
    unittest.main()
'''

# An unsafe tool the Tool Engineer might produce by mistake — the demo's
# --failure path shows it being rejected before it can run.
UNSAFE_SOURCE = b'''import os
import json
import sys
data = json.load(sys.stdin)
os.system("id")
print(json.dumps({"transmitted": 0, "received": 0, "loss_percent": 0.0}))
'''


def _new_env(tmp: Path):
    state_path = tmp / "state" / "lesson.json"
    trace = Trace(new_run_id(), "v1.1", base_dir=tmp, learner_id="demo-learner")
    gov = Governor(curriculum_mod.load(), trace=trace, state_path=state_path)
    learner = LearnerModel(tmp / "state" / "learner.json")
    workspace = tmp / "state" / "workspace" / trace.run_id
    workspace.mkdir(parents=True, exist_ok=True)
    return gov, trace, learner, workspace


def _timeline(trace: Trace) -> None:
    from packetlab.lab.trace import read_trace
    print("\n--- run trace timeline ---")
    for event in read_trace(trace.path):
        print(f"{event.get('seq'):>3}  {event.get('component', ''):<9} "
              f"{event.get('event', ''):<22} "
              f"{event.get('rule') or event.get('status') or ''}")
    ok, problems = verify_chain(trace.path)
    print(f"--- hash chain: {'VERIFIED' if ok else 'BROKEN'} {problems} ---")


def run(failure: bool = False) -> int:
    with tempfile.TemporaryDirectory(prefix="packetlab-demo-") as tmp_str:
        tmp = Path(tmp_str)
        gov, trace, learner, workspace = _new_env(tmp)
        gov.start_lesson("v1.1", trace.run_id)
        print(f"Lesson v1.1 started (run {trace.run_id})")
        return _failure_path(gov, trace, learner, workspace, tmp) if failure \
            else _happy_path(gov, trace, learner, workspace, tmp)


def _happy_path(gov, trace, learner, workspace, tmp) -> int:
    concept = "icmp.echo-request-reply"

    pred = Action("record", concept_id=concept, phase="predicted")
    if gov.evaluate(pred).allowed:
        gov.commit(pred)
        learner.add_evidence(concept, "prediction",
                             f"{RECORDED} 'two requests, two replies, no loss on loopback'",
                             "v1.1", trace.run_id)
    print(f"{RECORDED} prediction recorded")

    argv = ["ping", "-c", "2", "127.0.0.1"]
    action = Action("run_command", category="ping")
    decision = gov.evaluate(action)
    policy = check_command(argv, "ping", workspace)
    print(f"governor: {decision.allowed} | policy: {policy.allowed}")
    result = run_restricted(argv, cwd=workspace, timeout_s=10, max_output_bytes=100000)
    trace.emit("runner", "command_executed", argv=argv, result=result.to_summary())
    gov.commit(action, outcome=result.to_summary())
    print(f"ping ran: {result.status}")

    obs = Action("record", concept_id=concept, phase="observed")
    gov.commit(obs)
    learner.add_evidence(concept, "observation",
                         "observed 2 transmitted / 2 received on lo", "v1.1", trace.run_id)

    matches = toolgen.lookup(["ping", "summary"], root=tmp)
    print(f"tool lookup: {len(matches)} existing match(es) -> generating a tool")
    spec, _ = ToolSpec.from_dict(TOOL_SPEC)
    artifacts = ToolArtifacts("icmp-echo-summary", tmp / "tools", spec,
                              TOOL_SOURCE, TOOL_TEST)
    gen = Action("generate_tool")
    gov.commit(gen)
    validation = toolgen.validate(spec, TOOL_SOURCE, TOOL_TEST, workspace,
                                  ["observe_network", "ping", "capture"])
    print(f"validation: {'PASS' if validation['ok'] else 'FAIL ' + str(validation['checks'])}")
    tests = toolgen.run_tests(artifacts, validation["source_sha256"],
                              validation["test_sha256"], workspace)
    print(f"unit tests: {tests.status}")
    toolgen.register(artifacts, validation, tests, generator="fixture",
                     root=tmp, trace=trace)

    invoke = Action("invoke_tool")
    gov.commit(invoke)
    invoked = toolgen.invoke("icmp-echo-summary",
                             {"ping_output": result.stdout}, workspace,
                             root=tmp, trace=trace)
    print(f"tool invoked: {invoked['status']} -> {invoked.get('outputs')}")

    exp = Action("record", concept_id=concept, phase="explained")
    gov.commit(exp)
    state = learner.add_evidence(
        concept, "explanation",
        f"{RECORDED} 'each request is paired to a reply by id/seq; loopback never lost one'",
        "v1.1", trace.run_id)
    print(f"{RECORDED} explanation recorded -> concept state: {state.state}")

    _timeline(trace)
    print(f"\nDemo complete. Concept '{concept}' reached: {state.state}")
    return 0 if state.state == "mastered" and invoked["status"] == "ok" else 1


def _failure_path(gov, trace, learner, workspace, tmp) -> int:
    print("\n=== failure & recovery demonstration ===")

    print("\n1) A command outside lesson scope is denied:")
    denied = gov.evaluate(Action("run_command", category="modify_neighbour_cache"))
    print(f"   modify_neighbour_cache in v1.1 -> allowed={denied.allowed} "
          f"({denied.reason})")

    print("\n2) An unsafe generated tool is rejected before it can run:")
    spec, _ = ToolSpec.from_dict(TOOL_SPEC)
    validation = toolgen.validate(spec, UNSAFE_SOURCE, TOOL_TEST, workspace,
                                  ["ping"])
    print(f"   validation ok={validation['ok']} "
          f"source_ast={validation['checks']['source_ast']}")
    trace.emit("toolgen", "tool_validated", tool_id=spec.id, ok=validation["ok"],
               findings=validation["checks"])

    print("\n3) The quarantine kill-switch removes a registered tool:")
    # Register the SAFE tool first so quarantine has a real status to flip.
    good_val = toolgen.validate(spec, TOOL_SOURCE, TOOL_TEST, workspace, ["ping"])
    arts = ToolArtifacts("icmp-echo-summary", tmp / "tools", spec,
                         TOOL_SOURCE, TOOL_TEST)
    good_tests = toolgen.run_tests(arts, good_val["source_sha256"],
                                   good_val["test_sha256"], workspace)
    toolgen.register(arts, good_val, good_tests, generator="fixture", root=tmp,
                     trace=trace)
    before = len(toolgen.lookup(["ping", "summary"], root=tmp))
    toolgen.quarantine("icmp-echo-summary", "demo: exercising the kill-switch",
                       root=tmp, trace=trace)
    after = len(toolgen.lookup(["ping", "summary"], root=tmp))
    invoked = toolgen.invoke("icmp-echo-summary", {"ping_output": ""}, workspace,
                             root=tmp, trace=trace)
    print(f"   lookup before={before}, after quarantine={after}; "
          f"invoke -> {invoked['status']}")

    print("\n4) A runaway command is killed at the wall-clock deadline:")
    timed = run_restricted(["sleep", "30"], cwd=workspace, timeout_s=2,
                           max_output_bytes=1000)
    trace.emit("runner", "command_executed", argv=["sleep", "30"],
               result=timed.to_summary())
    print(f"   sleep 30 with 2s timeout -> {timed.status} in {timed.duration_ms}ms")

    print("\n5) The lesson can be aborted with a recorded reason:")
    gov.abort_lesson("demo failure path")
    _timeline(trace)
    ok = (not denied.allowed and not validation["ok"] and timed.status == "timeout"
          and after == 0 and invoked["status"] == "quarantined")
    print(f"\nRecovery demo {'PASSED' if ok else 'FAILED'}: "
          "each failure produced a structured, traced outcome")
    return 0 if ok else 1
