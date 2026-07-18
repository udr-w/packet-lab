"""Health check: documentation size caps + machine/human state consistency.

Wraps the existing scripts/lab-doctor.py (doc size caps) and adds the checks
the control plane needs to stay honest:

- curriculum.json vs ROADMAP.md: every version's status must agree, so a
  lesson cannot be "complete" in one file and "planned" in the other.
- progress percentage: ROADMAP.md's headline number must match the value
  computed from curriculum status.
- terminology: docs/ must not describe the single reasoning agent in plural
  "agents"/"multi-agent" terms (guards against multi-agent theatre drift).

Exit code 1 on any FAIL, mirroring lab-doctor's contract.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from packetlab.lab import curriculum as curriculum_mod

REPO = Path(__file__).resolve().parents[2]

# Words that would misrepresent the single-reasoning-agent architecture.
BANNED_DOC_PHRASES = ("multi-agent", "swarm of agents", "fully autonomous")


def _run_lab_doctor() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "lab-doctor.py")],
        capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def _roadmap_statuses() -> dict:
    """Map version number -> textual status from ROADMAP.md."""
    text = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    statuses = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^Version (\d+)", line.strip())
        if m:
            current = int(m.group(1))
        sm = re.match(r"^Status:\s*(.+)$", line.strip())
        if sm and current is not None:
            statuses[current] = sm.group(1).lower()
            current = None
    return statuses


def check_consistency() -> list[str]:
    problems = []
    curric = curriculum_mod.load()
    roadmap = _roadmap_statuses()

    by_version: dict[int, list] = {}
    for lesson in curric.lessons.values():
        major = int(lesson.lesson_id.split(".")[0].lstrip("v"))
        by_version.setdefault(major, []).append(lesson)

    for version, lessons in by_version.items():
        all_complete = all(le.status == "complete" for le in lessons)
        any_progress = any(le.status == "in_progress" for le in lessons)
        rm = roadmap.get(version, "")
        if all_complete and "complete" not in rm:
            problems.append(f"version {version}: curriculum=complete but "
                            f"ROADMAP says '{rm}'")
        if any_progress and "complete" in rm:
            problems.append(f"version {version}: curriculum=in_progress but "
                            f"ROADMAP says complete")

    _, total, percent = curric.progress()
    rm_text = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    pm = re.search(r"(\d+)\s*/\s*(\d+) versions complete", rm_text)
    if pm:
        rm_complete, rm_total = int(pm.group(1)), int(pm.group(2))
        computed_complete = curric.progress()[0]
        if rm_complete != computed_complete or rm_total != total:
            problems.append(
                f"ROADMAP progress {rm_complete}/{rm_total} disagrees with "
                f"curriculum {computed_complete}/{total}")
    percent_m = re.search(r"(\d+)%\s+of the learning program", rm_text)
    if percent_m and int(percent_m.group(1)) != percent:
        problems.append(f"ROADMAP percentage {percent_m.group(1)}% != computed {percent}%")
    return problems


def check_terminology() -> list[str]:
    problems = []
    docs = list((REPO / "docs").rglob("*.md")) + [REPO / "README.md"]
    for path in docs:
        if not path.exists():
            continue
        low = path.read_text(encoding="utf-8", errors="replace").lower()
        negations = ("not ", "no ", "never ", "isn't ", "is not", "single ",
                     "one ", "rather than ", "reject", "avoid", "instead of",
                     "true multi-agent", "not a ", "would be", "misrepresent",
                     "dishonest")
        for phrase in BANNED_DOC_PHRASES:
            # Allow the phrase when a negation/rejection marker sits nearby on
            # either side — ADRs legitimately discuss why the system is NOT this.
            for m in re.finditer(re.escape(phrase), low):
                window = low[max(0, m.start() - 120):m.end() + 120]
                if any(neg in window for neg in negations):
                    continue
                problems.append(f"{path.relative_to(REPO)}: uses '{phrase}' "
                                "without an explicit negation")
    return problems


def run() -> int:
    print("Packet Lab — health check\n")
    code, output = _run_lab_doctor()
    print(output.rstrip())
    print()

    consistency = check_consistency()
    terminology = check_terminology()

    print("Consistency (curriculum <-> ROADMAP):")
    if consistency:
        for problem in consistency:
            print(f"  FAIL  {problem}")
    else:
        print("  OK  curriculum and ROADMAP agree")

    print("Terminology (single-agent honesty):")
    if terminology:
        for problem in terminology:
            print(f"  FAIL  {problem}")
    else:
        print("  OK  no misleading multi-agent language in docs")

    failed = code != 0 or consistency or terminology
    print("\nResult:", "FAIL" if failed else "OK")
    return 1 if failed else 0
