# Contributing

Packet Lab is a teaching lab wrapped in a deterministic control plane. Changes
should keep both honest: the teaching identity (Linux networking from first
principles) and the control-plane discipline (safety in code, not prompts).

## Golden rules

- **Standard library only** for `packetlab/lab/`. The live viewer may use Rich;
  the control plane must not add dependencies.
- **Files under 500 lines.** Split a module before it grows past that.
- **Atomic, locked state writes.** All state mutation goes through
  `statefile.py` (`update_json` / `atomic_write_json`), never a bare write.
- **No new root requirements**, **no secrets**, **no shell** (argv lists only).
- **Terminology:** the system has *one* reasoning agent. Do not describe it as
  "multi-agent" or a "swarm" in `docs/` without an explicit negation — `lab
  doctor` fails the build if you do.
- **Safety-sensitive code needs tests on both the accept and the reject path.**
  A gate tested only one way may block everything or nothing.

## Definition of done

```bash
python3 -m packetlab.lab doctor      # docs caps + curriculum/ROADMAP consistency + terminology
./packet-lab.sh test                 # 163 unit tests
./packet-lab.sh eval                 # 54 conformance evals
```

All three must pass (non-zero exit fails CI). If you touched a lesson's status,
`doctor` will fail unless `ROADMAP.md` and `curriculum/curriculum.json` agree.

## How to add …

### A command category

1. Add an entry to `COMMAND_CATEGORIES` in `policy.py` with a `BinaryRule` per
   binary. For anything that can write files or spawn processes, prefer an
   **allow-list** of flags (`allowed_flags=`) over a deny-list — see the
   `tcpdump` rule.
2. Grant it to the lessons that need it via `permitted_categories` in
   `curriculum.json`.
3. Add `test_policy.py` cases covering an accepted and a rejected invocation.

### A curriculum lesson

1. Add the lesson to `curriculum/curriculum.json` with `budgets`, `concepts`
   (each concept id must exist in the top-level `concepts` map), `in_scope`,
   `out_of_scope`, `permitted_categories`, and `completion_criteria`.
2. Keep `ROADMAP.md` in step — `lab doctor` cross-checks status and the progress
   percentage.
3. The loader (`curriculum.py`) rejects dangling concept/prerequisite/category
   references, so run `doctor` to validate.

### An eval

Add a JSON fixture under `evals/fixtures/<category>/`. It is data, not code:
pick a `target` enforcement point, provide `input`, and assert with `expect`.
See `docs/evaluation-strategy.md` for the envelope. If you find yourself writing
Python to test agent behaviour, target the deterministic enforcement point
instead — that is what the evals are for.

### A generated tool (or a fixture tool)

A tool is three files the agent produces and the control plane validates:
`spec.json` (a `ToolSpec`), `tool.py` (stdlib only, with a `main()` guard so
importing it in the test does nothing), and `test_tool.py` (may import
`unittest` and the module under test `tool`). Validate it end to end with:

```bash
python3 -m packetlab.lab tool validate --spec spec.json --source tool.py --test test_tool.py
```

Never widen `astcheck.ALLOWED_IMPORTS` or relax a forbidden name to make a tool
pass — fix the tool. The allow-list is the load-bearing gate (see the threat
model).

## Layout

```
packetlab/lab/     control plane (stdlib only)
scripts/           viewer entry + lab-doctor size caps
curriculum/        curriculum graph
tests/             unit tests (safety mechanisms)
evals/             conformance evals + fixtures
docs/              architecture, threat model, ADRs, lessons, knowledge, examples
```

## Review stance

The interesting part of this project is the control around the agent. A change
that adds capability but weakens a boundary — a new import in the allow-list, a
deny-list where an allow-list belongs, a state write outside `statefile` — will
be sent back even if it makes a lesson smoother. Boundaries first.
