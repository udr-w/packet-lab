"""packetlab.lab command-line interface.

One operator surface for the tutoring agent. Every guarded action flows
governor.evaluate -> execute -> governor.commit, and every important step
lands in the run trace. Commands are intentionally few and each does one thing.

    python3 -m packetlab.lab resume [--json|--verbose]
    python3 -m packetlab.lab preflight [--json]
    python3 -m packetlab.lab doctor
    python3 -m packetlab.lab lesson start|status|close|abort
    python3 -m packetlab.lab record prediction|observation|explanation|skip
    python3 -m packetlab.lab run --category C -- argv...
    python3 -m packetlab.lab tool lookup|validate|invoke|list|cleanup
    python3 -m packetlab.lab learner show|reset
    python3 -m packetlab.lab inspect <run-id> [--verify]
    python3 -m packetlab.lab demo [--failure]
    python3 -m packetlab.lab eval
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

from packetlab.lab import curriculum as curriculum_mod
from packetlab.lab import toolgen, untrusted
from packetlab.lab.governor import Action, Governor, NoActiveLessonError
from packetlab.lab.learner import LearnerModel
from packetlab.lab.policy import check_command
from packetlab.lab.profiles import LearnerProfiles, validate_learner_id
from packetlab.lab.runner import run_restricted
from packetlab.lab.specs import ToolSpec
from packetlab.lab.statefile import load_json
from packetlab.lab.trace import (Trace, list_runs, new_run_id, read_trace,
                                 repo_root, runs_dir, verify_chain)

STATE_DIR = repo_root() / "state"


class NoActiveLearner(RuntimeError):
    pass


def _profiles() -> LearnerProfiles:
    profiles = LearnerProfiles(STATE_DIR)
    profiles.migrate_legacy_if_present()
    return profiles


def _active_learner() -> str:
    """The selected learner id, or raise NoActiveLearner with guidance."""
    active = _profiles().get_active()
    if active is None:
        raise NoActiveLearner(
            "no active learner. Create one with:\n"
            "  packetlab.lab learner create <learner-id>\n"
            "then it becomes active automatically.")
    return active


def _learner_dir(learner_id: str) -> Path:
    return _profiles().learner_dir(learner_id)


def _lesson_state_path(learner_id: str) -> Path:
    return _learner_dir(learner_id) / "lesson.json"


def _workspace(learner_id: str, run_id: str) -> Path:
    ws = _learner_dir(learner_id) / "workspace" / run_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _active_trace(learner_id: str) -> Trace | None:
    state = load_json(_lesson_state_path(learner_id), default={})
    run_id = state.get("run_id")
    if not run_id or state.get("closed"):
        return None
    return Trace.open_existing(run_id, base_dir=_learner_dir(learner_id))


def _governor(learner_id: str, trace: Trace | None = None) -> Governor:
    return Governor(curriculum_mod.load(), trace=trace,
                    state_path=_lesson_state_path(learner_id))


def _learner_model(learner_id: str) -> LearnerModel:
    return LearnerModel(_learner_dir(learner_id) / "learner.json")


def _out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


# ---- commands ------------------------------------------------------------

def cmd_resume(args) -> int:
    """Read-only resume snapshot: learner, lesson, next step, preflight advice.

    This is the fast path a lesson resume starts with — one invocation, no
    doctor, no tests, no network, no run creation, no state mutation.
    """
    from packetlab.lab import resume as resume_mod
    snapshot = resume_mod.build_snapshot(state_dir=STATE_DIR)
    if args.json:
        _out(snapshot)
    elif args.verbose:
        print(resume_mod.render_verbose(snapshot))
    else:
        print(resume_mod.render_learner(snapshot))
    return 0 if snapshot["status"] in ("resume", "fresh") else 1


def cmd_preflight(args) -> int:
    """Run the snapshot's recommended capability checks. PRIVATE output.

    Presence/capability checks only — no packets, no learner-state writes.
    Any representative live probe (e.g. a disposable-hostname dig) remains an
    explicit assistant action guided by the plan this prints.
    """
    from packetlab.lab import preflight as preflight_mod
    from packetlab.lab import resume as resume_mod
    snapshot = resume_mod.build_snapshot(state_dir=STATE_DIR)
    plan = snapshot.get("preflight",
                        {"recommended": False, "outcome": "none_needed",
                         "checks": []})
    results = preflight_mod.run_checks(plan)
    payload = {"private": True, "plan": plan, "results": results,
               "learner_message_on_failure":
                   preflight_mod.learner_message_for_failure(results)}
    if args.json:
        _out(payload)
    else:
        print("PRIVATE preflight diagnostics — do not show to the learner")
        _out(payload)
    return 0 if results["ok"] else 1


def cmd_doctor(_args) -> int:
    from packetlab.lab import doctor
    return doctor.run()


def cmd_lesson(args) -> int:
    try:
        learner_id = _active_learner()
    except NoActiveLearner as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.action == "start":
        run_id = new_run_id()
        trace = Trace(run_id, args.lesson_id, base_dir=_learner_dir(learner_id),
                      learner_id=learner_id)
        gov = _governor(learner_id, trace=trace)
        try:
            state = gov.start_lesson(args.lesson_id, run_id)
        except ValueError as exc:
            print(f"cannot start: {exc}", file=sys.stderr)
            return 1
        _workspace(learner_id, run_id)
        _out({"learner": learner_id, "started": args.lesson_id, "run_id": run_id,
              "objective": state["objective"]})
        return 0
    if args.action == "status":
        status = _governor(learner_id).status()
        status["learner"] = learner_id
        _out(status)
        return 0
    if args.action == "close":
        gov = _governor(learner_id, trace=_active_trace(learner_id))
        try:
            state = gov.close_lesson(args.confirm or [])
        except (ValueError, NoActiveLessonError) as exc:
            print(f"cannot close: {exc}", file=sys.stderr)
            return 1
        _out({"learner": learner_id, "closed": state["lesson_id"]})
        return 0
    if args.action == "abort":
        gov = _governor(learner_id, trace=_active_trace(learner_id))
        gov.abort_lesson(args.reason or "unspecified")
        _out({"learner": learner_id, "aborted": True})
        return 0
    return 1


def cmd_record(args) -> int:
    try:
        learner_id = _active_learner()
    except NoActiveLearner as exc:
        print(exc, file=sys.stderr)
        return 1
    trace = _active_trace(learner_id)
    gov = _governor(learner_id, trace=trace)
    phase_map = {"prediction": "predicted", "observation": "observed",
                 "explanation": "explained", "skip": "skip"}
    phase = phase_map[args.kind]
    action = Action("record", concept_id=args.concept, phase=phase)
    decision = gov.evaluate(action)
    if not decision.allowed:
        _out({"learner": learner_id, "recorded": False,
              "reason": decision.reason, "rule": decision.rule})
        return 1
    gov.commit(action)
    concept = _learner_model(learner_id).add_evidence(
        args.concept, args.kind, args.text,
        gov.status().get("lesson_id", ""), trace.run_id if trace else None)
    _out({"learner": learner_id, "recorded": True, "concept": args.concept,
          "state": concept.state})
    return 0


def cmd_run(args) -> int:
    try:
        learner_id = _active_learner()
    except NoActiveLearner as exc:
        print(exc, file=sys.stderr)
        return 1
    trace = _active_trace(learner_id)
    gov = _governor(learner_id, trace=trace)
    argv = args.argv
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("run needs a command after --", file=sys.stderr)
        return 2

    state = gov.status()
    run_id = state.get("run_id")
    if not run_id or state.get("closed"):
        print("no active lesson; run `lesson start` first", file=sys.stderr)
        return 1
    workspace = _workspace(learner_id, run_id)

    action = Action("run_command", category=args.category, detail={"argv": argv})
    decision = gov.evaluate(action)
    if not decision.allowed:
        _out({"ran": False, "reason": decision.reason, "rule": decision.rule})
        return 1

    policy_decision = check_command(argv, args.category, workspace)
    if trace:
        trace.emit("policy", "command_check", argv=argv, category=args.category,
                   allowed=policy_decision.allowed, rule=policy_decision.rule,
                   reason=policy_decision.reason)
    if not policy_decision.allowed:
        _out({"ran": False, "reason": policy_decision.reason,
              "rule": policy_decision.rule})
        return 1

    result = run_restricted(argv, cwd=workspace, timeout_s=args.timeout,
                            max_output_bytes=200_000)
    if trace:
        trace.emit("runner", "command_executed", argv=argv,
                   result=result.to_summary())
        # Flag (do not act on) injection-shaped text in the command output, so a
        # reviewer can see when captured data tried to steer the agent. Detection
        # for the audit trail — the wrapping below is what treats it as data.
        flags = untrusted.looks_like_injection(result.stdout + result.stderr)
        if flags:
            trace.emit("untrusted", "injection_flags_in_output", argv=argv,
                       flags=flags)
    gov.commit(action, outcome=result.to_summary())

    observation = sync_observation(
        gov, _learner_model(learner_id), args.observation_concept,
        args.observation_note or f"ran {' '.join(argv[:3])}",
        state.get("lesson_id", ""), run_id, run_ok=result.status == "ok")

    print(untrusted.render(f"command:{argv[0]}", result.stdout))
    if result.stderr.strip():
        print(untrusted.render(f"command:{argv[0]}:stderr", result.stderr))
    _out({"learner": learner_id, "status": result.status,
          "exit_code": result.exit_code, "duration_ms": result.duration_ms,
          "observation": observation})
    return 0 if result.status == "ok" else 1


def sync_observation(gov, learner, concept, note, lesson_id, run_id, run_ok):
    """Record an observation in the governor phase AND the learner model together.

    The governor is the authority. An observation is recorded only if the run
    succeeded and the governor permits the observed transition (a prediction or
    skip exists for the concept). This keeps the two sources of truth in step —
    the integration bug this replaced recorded the learner observation without
    advancing the governor phase, so a later explanation was wrongly blocked.
    """
    result = {"requested": bool(concept), "recorded": False}
    if not concept:
        return result
    obs_action = Action("record", concept_id=concept, phase="observed")
    decision = gov.evaluate(obs_action)
    if not run_ok:
        result["reason"] = "command did not succeed; no observation recorded"
    elif not decision.allowed:
        result["reason"] = f"governor blocked the observation: {decision.reason}"
    else:
        gov.commit(obs_action)
        learner.add_evidence(concept, "observation", note, lesson_id, run_id)
        result["recorded"] = True
    return result


def cmd_experiment(args) -> int:
    """Validate a structured experiment spec, and check its steps against policy.

    An ExperimentSpec separates the educational reasoning (objective, prediction,
    expected observations, reflection) from execution. Validating it here — and
    cross-checking every step's argv against the command policy — lets the
    Experiment Designer's plan be reviewed before any command runs.
    """
    from packetlab.lab.specs import ExperimentSpec
    spec, result = ExperimentSpec.from_dict(load_json(Path(args.spec)))
    if spec is None:
        _out({"valid": False, "errors": result.errors})
        return 1
    with tempfile.TemporaryDirectory() as ws:
        step_checks = []
        for i, step in enumerate(spec.steps + spec.cleanup):
            decision = check_command(step.argv, step.category, Path(ws))
            step_checks.append({"argv": step.argv, "category": step.category,
                                "allowed": decision.allowed, "rule": decision.rule})
    all_ok = all(s["allowed"] for s in step_checks)
    _out({"valid": True, "experiment": spec.id, "objective": spec.objective,
          "safety_class": spec.safety_class, "steps_policy_ok": all_ok,
          "steps": step_checks})
    return 0 if all_ok else 1


def cmd_tool(args) -> int:
    # Generated tools are learner-local: a tool that succeeded for one learner
    # is not automatically trusted for another (see docs/tool-lifecycle.md).
    try:
        learner_id = _active_learner()
    except NoActiveLearner as exc:
        print(exc, file=sys.stderr)
        return 1
    root = _learner_dir(learner_id)
    trace = _active_trace(learner_id)
    if args.action == "lookup":
        _out({"learner": learner_id, "matches": toolgen.lookup(args.keywords, root=root)})
        return 0
    if args.action == "list":
        registry = load_json(toolgen.registry_path(root), default={"tools": []})
        registry["learner"] = learner_id
        _out(registry)
        return 0
    if args.action == "validate":
        return _tool_validate(args, learner_id, trace)
    if args.action == "invoke":
        state = load_json(_lesson_state_path(learner_id), default={})
        run_id = state.get("run_id") or new_run_id()
        inputs = json.loads(args.inputs) if args.inputs else {}
        result = toolgen.invoke(args.tool_id, inputs, _workspace(learner_id, run_id),
                                root=root, trace=trace)
        result["learner"] = learner_id
        _out(result)
        return 0 if result.get("status") == "ok" else 1
    if args.action == "cleanup":
        removed = toolgen.cleanup(args.lesson_id, root=root, trace=trace)
        _out({"learner": learner_id, "removed": removed})
        return 0
    return 1


def _tool_validate(args, learner_id: str, trace) -> int:
    spec_data = load_json(Path(args.spec))
    spec, spec_result = ToolSpec.from_dict(spec_data)
    if spec is None:
        _out({"valid": False, "errors": spec_result.errors})
        return 1
    source = Path(args.source).read_bytes()
    test_source = Path(args.test).read_bytes()
    state = load_json(_lesson_state_path(learner_id), default={})
    run_id = state.get("run_id") or new_run_id()
    workspace = _workspace(learner_id, run_id)
    lesson = curriculum_mod.load().lesson(spec.lesson_id)
    permitted = list(lesson.permitted_categories) if lesson else []
    findings = toolgen.validate(spec, source, test_source, workspace, permitted)
    if trace:
        trace.emit("toolgen", "tool_validated", tool_id=spec.id, ok=findings["ok"],
                   findings=findings["checks"])
    _out({"learner": learner_id, "valid": findings["ok"],
          "findings": findings["checks"]})
    return 0 if findings["ok"] else 1


def cmd_learner(args) -> int:
    profiles = _profiles()
    if args.action == "create":
        norm, err = validate_learner_id(args.learner_id)
        if norm is None:
            print(f"invalid learner id: {err}", file=sys.stderr)
            return 2
        try:
            profile = profiles.create(norm, display_name=args.name)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _out({"created": profile.learner_id, "display_name": profile.display_name,
              "active": profiles.get_active() == profile.learner_id})
        return 0
    if args.action == "list":
        active = profiles.get_active()
        _out({"active": active,
              "learners": [{"id": lid, "active": lid == active}
                           for lid in profiles.list()]})
        return 0
    if args.action == "use":
        try:
            active = profiles.set_active(args.learner_id)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _out({"active": active})
        return 0
    if args.action == "show":
        try:
            learner_id = _active_learner()
        except NoActiveLearner as exc:
            print(exc, file=sys.stderr)
            return 1
        model = _learner_model(learner_id)
        if args.concept:
            out = model.concept(args.concept).__dict__
        else:
            out = model.summary()
        out["learner"] = learner_id
        _out(out)
        return 0
    if args.action == "reset":
        target = args.learner_id or profiles.get_active()
        if not target:
            print("no learner to reset", file=sys.stderr)
            return 1
        if not args.force:
            print(f"refusing to reset '{target}' without --force "
                  "(this wipes their progress)", file=sys.stderr)
            return 1
        try:
            profiles.reset(target)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _out({"reset": target})
        return 0
    return 1


def cmd_inspect(args) -> int:
    if args.file:
        path = Path(args.file)
        label = args.file
    else:
        try:
            learner_id = _active_learner()
        except NoActiveLearner as exc:
            print(exc, file=sys.stderr)
            return 1
        base = _learner_dir(learner_id)
        path = runs_dir(base) / args.run_id / "trace.jsonl"
        label = f"{learner_id}/{args.run_id}"
    if not path.exists():
        target = args.file or args.run_id
        print(f"no trace at {target}", file=sys.stderr)
        if not args.file:
            print("known runs: " + ", ".join(list_runs(base)), file=sys.stderr)
        return 1
    events = read_trace(path)
    if args.verify:
        ok, problems = verify_chain(path)
        _out({"trace": label, "events": len(events), "chain_ok": ok,
              "problems": problems})
        return 0 if ok else 1
    if args.timeline:
        for event in events:
            print(f"{event.get('seq'):>3} {event.get('ts', '')[11:19]} "
                  f"{event.get('component', ''):<9} {event.get('event', '')} "
                  f"{event.get('rule') or event.get('status') or ''}")
        return 0
    _out({"trace": label, "event_count": len(events), "events": events})
    return 0


def cmd_demo(args) -> int:
    from packetlab.lab import demo
    return demo.run(failure=args.failure)


def cmd_eval(_args) -> int:
    from evals import run_evals
    return run_evals.main([])


# ---- parser --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="packetlab.lab",
                                     description="Packet Lab control plane")
    sub = parser.add_subparsers(dest="command", required=True)

    resume = sub.add_parser("resume", help="fast read-only resume snapshot")
    resume.add_argument("--json", action="store_true",
                        help="machine-readable snapshot")
    resume.add_argument("--verbose", action="store_true",
                        help="learner view plus operator diagnostics")

    pre = sub.add_parser("preflight",
                         help="run private capability checks for the next step")
    pre.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="documentation + consistency health check")

    lesson = sub.add_parser("lesson", help="lesson lifecycle")
    lesson_sub = lesson.add_subparsers(dest="action", required=True)
    start = lesson_sub.add_parser("start")
    start.add_argument("lesson_id")
    lesson_sub.add_parser("status")
    close = lesson_sub.add_parser("close")
    close.add_argument("--confirm", action="append", help="a met completion criterion")
    abort = lesson_sub.add_parser("abort")
    abort.add_argument("--reason", required=True)

    record = sub.add_parser("record", help="record learner evidence")
    record.add_argument("kind", choices=["prediction", "observation",
                                         "explanation", "skip"])
    record.add_argument("concept")
    record.add_argument("--text", default="", help="evidence summary")

    run = sub.add_parser("run", help="run a guarded command")
    run.add_argument("--category", required=True)
    run.add_argument("--timeout", type=int, default=20)
    run.add_argument("--observation-concept", dest="observation_concept")
    run.add_argument("--observation-note", dest="observation_note")
    run.add_argument("argv", nargs=argparse.REMAINDER)

    experiment = sub.add_parser("experiment",
                                help="validate a structured experiment spec")
    experiment.add_argument("action", choices=["validate"])
    experiment.add_argument("--spec", required=True)

    tool = sub.add_parser("tool", help="generated-tool lifecycle")
    tool_sub = tool.add_subparsers(dest="action", required=True)
    lk = tool_sub.add_parser("lookup")
    lk.add_argument("keywords", nargs="+")
    tool_sub.add_parser("list")
    val = tool_sub.add_parser("validate")
    val.add_argument("--spec", required=True)
    val.add_argument("--source", required=True)
    val.add_argument("--test", required=True)
    inv = tool_sub.add_parser("invoke")
    inv.add_argument("tool_id")
    inv.add_argument("--inputs", help="JSON object of inputs")
    cl = tool_sub.add_parser("cleanup")
    cl.add_argument("lesson_id")

    learner = sub.add_parser("learner", help="learner profiles and mastery")
    learner_sub = learner.add_subparsers(dest="action", required=True)
    create = learner_sub.add_parser("create", help="create a learner profile")
    create.add_argument("learner_id")
    create.add_argument("--name", help="optional display name")
    learner_sub.add_parser("list", help="list local learner profiles")
    use = learner_sub.add_parser("use", help="set the active learner")
    use.add_argument("learner_id")
    show = learner_sub.add_parser("show", help="show the active learner's mastery")
    show.add_argument("--concept")
    reset = learner_sub.add_parser("reset", help="wipe a learner's progress")
    reset.add_argument("learner_id", nargs="?",
                       help="learner to reset (default: active)")
    reset.add_argument("--force", action="store_true",
                       help="required: reset is destructive")

    inspect = sub.add_parser("inspect", help="inspect a run trace")
    inspect.add_argument("run_id", nargs="?",
                         help="a run id under the active learner's runs/")
    inspect.add_argument("--file", help="inspect a trace file directly (e.g. a "
                         "committed example under docs/examples/)")
    inspect.add_argument("--verify", action="store_true", help="verify the hash chain")
    inspect.add_argument("--timeline", action="store_true", help="compact timeline")

    demo = sub.add_parser("demo", help="run the scripted end-to-end demo")
    demo.add_argument("--failure", action="store_true",
                      help="demonstrate failure and recovery paths")

    sub.add_parser("eval", help="run control-plane conformance evals")
    return parser


DISPATCH = {
    "resume": cmd_resume, "preflight": cmd_preflight,
    "doctor": cmd_doctor, "lesson": cmd_lesson, "record": cmd_record,
    "run": cmd_run, "experiment": cmd_experiment, "tool": cmd_tool,
    "learner": cmd_learner, "inspect": cmd_inspect, "demo": cmd_demo,
    "eval": cmd_eval,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return DISPATCH[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
