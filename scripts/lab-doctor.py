#!/usr/bin/env python3
"""lab-doctor.py — documentation health monitor for the Packet Lab.

Keeps the knowledge structure from bloating again by enforcing per-file
size caps and flagging the anti-patterns that caused the original problem
(a single unbounded narrative log + a growing "Completed Previously" section
in TASK.md).

Run before starting the next lesson:

    python3 scripts/lab-doctor.py

Exit code 0 if everything is OK/absent, 1 if any FAIL cap is breached.
WARN alone does not fail the check. Stdlib only, no third-party deps.
"""

import glob
import os
import re
import sys

# Repo root is the parent of this script's directory (scripts/lab-doctor.py),
# so paths resolve correctly regardless of the current working directory.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# CAP POLICY — the single source of truth for size limits.
# Keys are paths/globs relative to the repo root. Sizes are in KB.
# `warn_kb` is a soft limit (report WARN); `fail_kb` is a hard limit
# (report FAIL, exit 1). A cap with no `fail_kb` can only WARN.
CAP_POLICY = {
    "TASK.md":                {"warn_kb": 6,  "fail_kb": 10},
    "docs/handover.md":       {"warn_kb": 8,  "fail_kb": 15},
    "docs/lessons/*.md":      {"warn_kb": 25},
    "docs/knowledge/*.md":    {"warn_kb": 40},
}

# Files that must NOT exist under the new structure. learning-handover.md was
# the original unbounded log; it should have been replaced by handover.md +
# lessons/ + knowledge/.
FORBIDDEN_FILES = [
    "docs/learning-handover.md",
]

KB = 1024.0


def size_status(size_bytes, policy):
    """Return (status, note) for a file's byte size against a cap policy."""
    warn = policy.get("warn_kb")
    fail = policy.get("fail_kb")
    size_kb = size_bytes / KB
    if fail is not None and size_kb > fail:
        return "FAIL", "over fail cap %d KB" % fail
    if warn is not None and size_kb > warn:
        return "WARN", "over warn cap %d KB" % warn
    return "OK", ""


def check_completed_section(path):
    """Warn if TASK.md still carries a 'Completed'/'Completed Previously'
    history section — that log belongs in docs/lessons/ now."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    # Match a markdown heading like '## Completed Previously' or '# Completed'.
    pattern = re.compile(r"(?im)^#{1,6}\s+completed\b.*$")
    m = pattern.search(text)
    if m:
        return m.group(0).strip()
    return None


def collect_rows():
    """Resolve the CAP_POLICY into a list of per-file result rows.

    Each row is a dict: path (repo-relative), size (bytes or None), status, note.
    """
    rows = []
    for pattern, policy in CAP_POLICY.items():
        abs_pattern = os.path.join(REPO_ROOT, pattern)
        if glob.has_magic(pattern):
            matches = sorted(glob.glob(abs_pattern))
            if not matches:
                # Glob with no matches: nothing to check, note it as absent.
                rows.append({
                    "path": pattern,
                    "size": None,
                    "status": "OK",
                    "note": "no files",
                })
                continue
            for match in matches:
                rel = os.path.relpath(match, REPO_ROOT)
                rows.append(_row_for_file(match, rel, policy))
        else:
            rows.append(_row_for_file(abs_pattern, pattern, policy))
    return rows


def _row_for_file(abs_path, rel_path, policy):
    if not os.path.isfile(abs_path):
        return {"path": rel_path, "size": None, "status": "OK", "note": "absent"}
    size_bytes = os.path.getsize(abs_path)
    status, note = size_status(size_bytes, policy)
    return {"path": rel_path, "size": size_bytes, "status": status, "note": note}


def collect_antipatterns():
    """Return a list of anti-pattern warning rows (path, status=WARN, note)."""
    warnings = []

    # Forbidden files that should have been removed/replaced.
    for rel in FORBIDDEN_FILES:
        abs_path = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(abs_path):
            warnings.append({
                "path": rel,
                "note": "should be removed (replaced by handover.md + lessons/ + knowledge/)",
            })

    # 'Completed' history section lingering in TASK.md.
    task_path = os.path.join(REPO_ROOT, "TASK.md")
    if os.path.isfile(task_path):
        heading = check_completed_section(task_path)
        if heading:
            warnings.append({
                "path": "TASK.md",
                "note": "contains history section '%s' (move to docs/lessons/)" % heading,
            })

    return warnings


def format_size(size_bytes):
    if size_bytes is None:
        return "-"
    return "%.1f KB" % (size_bytes / KB)


def main():
    rows = collect_rows()
    antipatterns = collect_antipatterns()

    # Column widths for an aligned report.
    path_w = max([len(r["path"]) for r in rows] + [len("FILE")])
    path_w = max(path_w, *[len(w["path"]) for w in antipatterns]) if antipatterns else path_w

    print("Packet Lab — documentation health")
    print("repo: %s" % REPO_ROOT)
    print()
    print("%-*s  %9s  %-6s  %s" % (path_w, "FILE", "SIZE", "STATUS", "NOTE"))
    print("%s  %9s  %-6s  %s" % ("-" * path_w, "-" * 9, "-" * 6, "-" * 4))

    file_count = 0
    total_bytes = 0
    any_fail = False

    for r in rows:
        if r["size"] is not None:
            file_count += 1
            total_bytes += r["size"]
        if r["status"] == "FAIL":
            any_fail = True
        print("%-*s  %9s  %-6s  %s" % (
            path_w, r["path"], format_size(r["size"]), r["status"], r["note"]))

    if antipatterns:
        print()
        print("Anti-patterns:")
        for w in antipatterns:
            print("%-*s  %9s  %-6s  %s" % (
                path_w, w["path"], "-", "WARN", w["note"]))

    print()
    print("Totals: %d file(s), %s (%d bytes)" % (
        file_count, format_size(total_bytes), total_bytes))

    if any_fail:
        print("Result: FAIL — a hard cap is breached; fix before the next lesson.")
        return 1
    print("Result: OK — no hard caps breached.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
