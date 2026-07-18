"""Private preflight planning — decide what to validate before a lesson step.

Packet Lab teaches from the learner's real machine, so before asking a
prediction question the assistant may privately verify that the planned
experiment still works (tool present, capture capability intact, resolver
reachable). This module keeps that verification *minimal, private, and
non-contaminating*:

- `plan(lesson, next_phase)` is a deterministic decision function: given the
  lesson's permitted command categories and where the learner is, it returns
  which checks (if any) are worth running. No giant planning framework.
- Preflight results are operator diagnostics. They are never learner
  evidence, never advance mastery or the governor phase (nothing here touches
  learner state at all), and are never shown to the learner by default.
- Stateful experiments must not be warmed. For DNS the plan carries a
  disposable hostname (random label — cannot collide with any name the
  learner will query) and lists the learner's reserved targets as forbidden.

Honest residual risks are declared in the plan itself (`residual_risks`):
e.g. a preflight DNS query still exercises the resolver path and populates a
negative-cache entry for the disposable label; interface counters tick. What
cannot be perfectly restored is documented, not hidden.

Outcomes:

    none_needed        nothing about the next step depends on the environment
    capability_only    binary/capability presence checks, no packets, no state
    lightweight        capability checks + one disposable representative probe,
                       deferred until after the learner's prediction is recorded
    unavailable        a required check already failed (set by run_checks)
"""

from __future__ import annotations

import shutil
import uuid

from packetlab.lab.curriculum import Lesson

OUTCOME_NONE = "none_needed"
OUTCOME_CAPABILITY_ONLY = "capability_only"
OUTCOME_LIGHTWEIGHT = "lightweight"
OUTCOME_UNAVAILABLE = "unavailable"

# Phases whose next step involves running something on the machine.
_EXPERIMENT_PHASES = (None, "theory", "predicted")

# Category -> the checks that make its experiments runnable.
# kind "binary": presence via shutil.which (no subprocess, no packets).
# kind "capability": a file capability that an apt upgrade may reset; verifying
# it needs `getcap`, so it runs only in the preflight executor, never in the
# resume snapshot.
_CATEGORY_CHECKS = {
    "capture": (
        {"id": "binary:tcpdump", "kind": "binary", "target": "tcpdump"},
        {"id": "capability:tcpdump", "kind": "capability",
         "target": "/usr/bin/tcpdump", "expect": "cap_net_raw"},
    ),
    "dns_query": (
        {"id": "binary:dig", "kind": "binary", "target": "dig"},
    ),
    "ping": (
        {"id": "binary:ping", "kind": "binary", "target": "ping"},
    ),
    # observe_network / read_system_file need nothing beyond coreutils.
}

# Categories whose experiments depend on state a probe could silently consume
# or warm (DNS caches today; ARP/conntrack lessons would extend this).
_STATEFUL_CATEGORIES = {"dns_query"}


def disposable_hostname(reserved: tuple[str, ...] = (),
                        token: str | None = None) -> str:
    """A throwaway DNS name guaranteed different from every reserved target.

    A random label under example.com: it will answer NXDOMAIN, which still
    proves the whole resolution path (stub -> router -> upstream) works,
    while the only cache entry it can create is for this label itself.
    """
    reserved_lower = {r.lower() for r in reserved}
    for _ in range(8):
        label = token or f"pl-preflight-{uuid.uuid4().hex[:10]}"
        name = f"{label}.example.com"
        if name.lower() not in reserved_lower:
            return name
        token = None  # a supplied token that collided is discarded
    raise RuntimeError("could not choose a disposable hostname")


def plan(lesson: Lesson | None, next_phase: str | None = None,
         reserved_targets: tuple[str, ...] = ()) -> dict:
    """Deterministic preflight decision for the lesson's next step."""
    if lesson is None or next_phase not in _EXPERIMENT_PHASES:
        return {"recommended": False, "outcome": OUTCOME_NONE,
                "reason": "the next step is conversational; nothing to validate",
                "checks": [], "contamination_controls": [],
                "residual_risks": []}

    checks = [dict(check) for category in lesson.permitted_categories
              for check in _CATEGORY_CHECKS.get(category, ())]
    if not checks:
        return {"recommended": False, "outcome": OUTCOME_NONE,
                "reason": "no environment-dependent categories in this lesson",
                "checks": [], "contamination_controls": [],
                "residual_risks": []}

    stateful = [c for c in lesson.permitted_categories
                if c in _STATEFUL_CATEGORIES]
    result = {
        "recommended": True,
        "outcome": OUTCOME_LIGHTWEIGHT if stateful else OUTCOME_CAPABILITY_ONLY,
        "reason": ("the next step needs live capture/lookup tools; verify "
                   "them privately before asking the learner to predict"),
        "checks": checks,
        "contamination_controls": [
            "preflight output is private operator diagnostics, never shown "
            "to the learner and never recorded as learner evidence",
            "preflight never calls `lab record` and never touches "
            "learner.json or lesson.json",
        ],
        "residual_risks": [],
    }
    if stateful:
        disposable = disposable_hostname(reserved_targets)
        result["disposable_hostname"] = disposable
        result["forbidden_targets"] = list(reserved_targets)
        result["contamination_controls"] += [
            "any representative DNS probe must use the disposable hostname, "
            "never a name the learner will query",
            "defer the live probe until after the learner's prediction is "
            "recorded, immediately before their experiment",
        ]
        result["residual_risks"] += [
            "a probe still exercises the resolver path and leaves a "
            "negative-cache entry for the disposable label",
            "interface packet counters advance during any probe",
        ]
    return result


def run_checks(plan_dict: dict) -> dict:
    """Execute the plan's capability checks. PRIVATE operator output.

    Runs only presence/capability checks — never the representative live
    probe (that stays an explicit, documented assistant action using the
    plan's disposable hostname). Touches no learner state.
    """
    results = []
    for check in plan_dict.get("checks", []):
        if check["kind"] == "binary":
            path = shutil.which(check["target"])
            results.append({**check, "ok": path is not None, "found": path})
        elif check["kind"] == "capability":
            results.append({**check, **_capability_check(check)})
        else:
            results.append({**check, "ok": False,
                            "error": f"unknown check kind {check['kind']}"})
    ok = all(r.get("ok") for r in results) if results else True
    outcome = plan_dict.get("outcome") if ok else OUTCOME_UNAVAILABLE
    return {"ok": ok, "outcome": outcome, "results": results, "private": True}


def _capability_check(check: dict) -> dict:
    import subprocess
    getcap = shutil.which("getcap")
    if getcap is None:
        return {"ok": False, "error": "getcap not installed"}
    try:
        proc = subprocess.run([getcap, check["target"]], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    ok = check.get("expect", "") in proc.stdout
    return {"ok": ok, "observed": proc.stdout.strip()}


def learner_message_for_failure(results: dict) -> str:
    """A jargon-free, honest message when a preflight check fails.

    Names the consequence for the lesson, not the machinery. The assistant
    must never invent expected results when validation contradicts the
    lesson's assumptions — this message is the honest fallback.
    """
    failed = [r for r in results.get("results", []) if not r.get("ok")]
    if not failed:
        return ""
    tools = sorted({r["target"].rsplit("/", 1)[-1] for r in failed})
    return ("Before we start: today's experiment needs "
            f"{' and '.join(tools)} on this machine, and my private check "
            "shows it isn't ready right now. Let's fix that together first — "
            "the lesson itself hasn't lost any progress.")
