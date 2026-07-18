#!/usr/bin/env python3
"""bench-resume.py — repeatable benchmark for the repository-controlled part
of a lesson resume. No LLM call anywhere.

Measures, for three synthetic learner shapes (unfinished DNS learner, fresh
learner, learner with a large evidence history):

  snapshot (warm)   build_snapshot() in-process, 5 runs each
  snapshot (cold)   `python3 -c "...build_snapshot..."` in a new interpreter,
                    3 runs each — interpreter + import + build
  preflight         plan + capability checks (no live probe, no packets)

Thresholds are deliberately coarse so CI stays stable (no flaky
sub-millisecond expectations):

  FAIL  cold snapshot max  > {COLD_FAIL_S} s   (a local state read taking
                                                seconds is a regression)
  WARN  cold snapshot max  > {COLD_WARN_S} s
  FAIL  warm snapshot max  > {WARM_FAIL_S} s

Exit 1 on FAIL, 0 otherwise.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from packetlab.lab import preflight as preflight_mod  # noqa: E402
from packetlab.lab import resume as resume_mod  # noqa: E402
from packetlab.lab.profiles import LearnerProfiles  # noqa: E402
from packetlab.lab.statefile import atomic_write_json  # noqa: E402

WARM_RUNS = 5
COLD_RUNS = 3
COLD_FAIL_S = 3.0
COLD_WARN_S = 1.0
WARM_FAIL_S = 1.0

UNFINISHED_DNS = {
    "lesson_id": "v3.0", "run_id": "run-bench", "closed": True,
    "aborted": True,
    "concept_phase": {"dns.resolution-chain": "predicted",
                      "dns.caching-ttl": "theory"},
    "stop_reasons": [{"ts": "2026-07-18T13:27:28+00:00",
                      "reason": "bench: ended early"}],
}


def make_learner(state: Path, learner_id: str, *, lesson=None,
                 evidence_entries: int = 0) -> None:
    profiles = LearnerProfiles(state)
    profiles.create(learner_id)
    ldir = profiles.learner_dir(learner_id)
    if lesson is not None:
        atomic_write_json(ldir / "lesson.json", lesson)
    if evidence_entries:
        evidence = [{"ts": f"2026-07-04T20:{i % 60:02d}:00+00:00",
                     "kind": "prediction", "summary": f"entry {i}" * 10,
                     "lesson_id": "v3.0", "run_id": None}
                    for i in range(evidence_entries)]
        atomic_write_json(ldir / "learner.json", {
            "version": 1,
            "concepts": {"dns.resolution-chain": {
                "state": "in_progress", "updated_at": "x",
                "evidence": evidence}}})


def time_warm(state: Path) -> list[float]:
    times = []
    for _ in range(WARM_RUNS):
        start = time.perf_counter()
        snapshot = resume_mod.build_snapshot(state_dir=state)
        times.append(time.perf_counter() - start)
        assert snapshot["status"] in ("resume", "fresh"), snapshot["status"]
    return times


def time_cold(state: Path) -> list[float]:
    code = ("import sys; sys.path.insert(0, {repo!r}); "
            "from pathlib import Path; "
            "from packetlab.lab import resume; "
            "s = resume.build_snapshot(state_dir=Path({state!r})); "
            "assert s['status'] in ('resume', 'fresh')").format(
                repo=str(REPO), state=str(state))
    times = []
    for _ in range(COLD_RUNS):
        start = time.perf_counter()
        subprocess.run([sys.executable, "-c", code], check=True, cwd=REPO)
        times.append(time.perf_counter() - start)
    return times


def stats(times: list[float]) -> dict:
    return {"min_ms": round(min(times) * 1000, 2),
            "median_ms": round(statistics.median(times) * 1000, 2),
            "max_ms": round(max(times) * 1000, 2)}


def bench_preflight() -> dict:
    from packetlab.lab.curriculum import load as load_curriculum
    lesson = load_curriculum().lesson("v3.0")

    start = time.perf_counter()
    plan = preflight_mod.plan(lesson, next_phase="theory")
    plan_s = time.perf_counter() - start

    per_check = []
    start_all = time.perf_counter()
    for check in plan["checks"]:
        start = time.perf_counter()
        result = preflight_mod.run_checks({"outcome": plan["outcome"],
                                           "checks": [check]})
        per_check.append({"id": check["id"],
                          "ok": result["ok"],
                          "ms": round((time.perf_counter() - start) * 1000, 2)})
    total_s = time.perf_counter() - start_all

    # Failure behaviour: a missing binary must degrade cleanly, not raise.
    start = time.perf_counter()
    failed = preflight_mod.run_checks(
        {"outcome": "capability_only",
         "checks": [{"id": "binary:missing", "kind": "binary",
                     "target": "bench-definitely-missing"}]})
    failure_ms = round((time.perf_counter() - start) * 1000, 2)

    return {"plan_ms": round(plan_s * 1000, 2),
            "checks": per_check,
            "total_checks_ms": round(total_s * 1000, 2),
            "execution": "sequential (each check is a local lookup; "
                         "concurrency would add more overhead than it saves)",
            "contamination_controls": plan["contamination_controls"],
            "network_activity": "none (presence/capability checks only)",
            "failed_check_behaviour": {
                "ok": failed["ok"], "outcome": failed["outcome"],
                "ms": failure_ms,
                "learner_message":
                    preflight_mod.learner_message_for_failure(failed)},
            }


def main() -> int:
    report: dict = {"snapshot": {}, "preflight": {}}
    problems: list[str] = []

    with tempfile.TemporaryDirectory() as d:
        scenarios = {}
        for name, kwargs in (
                ("unfinished_dns", {"lesson": UNFINISHED_DNS}),
                ("fresh", {}),
                ("large_history", {"lesson": UNFINISHED_DNS,
                                   "evidence_entries": 500})):
            state = Path(d) / name
            make_learner(state, "bench", **kwargs)
            scenarios[name] = state

        for name, state in scenarios.items():
            warm, cold = time_warm(state), time_cold(state)
            report["snapshot"][name] = {
                "warm": stats(warm), "cold_process": stats(cold),
                "runs": {"warm": WARM_RUNS, "cold": COLD_RUNS},
            }
            if max(cold) > COLD_FAIL_S:
                problems.append(f"{name}: cold snapshot {max(cold):.2f}s "
                                f"> {COLD_FAIL_S}s FAIL")
            elif max(cold) > COLD_WARN_S:
                print(f"WARN {name}: cold snapshot {max(cold):.2f}s "
                      f"> {COLD_WARN_S}s", file=sys.stderr)
            if max(warm) > WARM_FAIL_S:
                problems.append(f"{name}: warm snapshot {max(warm):.2f}s "
                                f"> {WARM_FAIL_S}s FAIL")

    report["snapshot"]["side_effects"] = "none (see tests/test_resume.py)"
    report["snapshot"]["network_activity"] = "none (enforced by test)"
    report["snapshot"]["command_count"] = 1
    report["preflight"] = bench_preflight()

    print(json.dumps(report, indent=2))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("\nResult: OK — within thresholds "
          f"(cold fail>{COLD_FAIL_S}s, warm fail>{WARM_FAIL_S}s)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
