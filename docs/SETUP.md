# Setup

How to get Packet Lab running on a fresh machine or a fresh clone, and how to
start the learning program once it's set up.

## 1. Prerequisites

- Linux (the lessons are about Linux networking specifically).
- Python 3.10+.
- `tcpdump`.
- `git`.
- The `python3-rich` package (the terminal viewer's UI library):

  ```bash
  sudo apt install python3-rich
  ```

## 2. Clone the repo

```bash
git clone <repo-url> packet-lab
cd packet-lab
```

## 3. Grant packet-capture capability (no sudo needed)

So the viewer and `tcpdump` can capture packets without running as root:

```bash
sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/tcpdump
```

Verify it took:

```bash
getcap /usr/bin/tcpdump
```

**Caveat:** an `apt upgrade` of `tcpdump` resets this capability. If capture
suddenly fails after a system upgrade, re-run `getcap /usr/bin/tcpdump` to
check, and re-apply the `setcap` command above if it's missing.

## 4. Run the documentation health check

```bash
python3 scripts/lab-doctor.py
```

This checks that TASK.md, docs/handover.md, docs/lessons/*.md, and
docs/knowledge/*.md are within their size caps and flags any stale
anti-patterns (e.g. a leftover "Completed" history section in TASK.md). Exit
code 0 means OK/WARN only; exit code 1 means a hard cap (FAIL) was breached
and should be fixed first.

## 5. (Optional) Run the packet viewer directly

```bash
python3 scripts/packetlab.py [mode] [interface]
```

- Currently available modes: `icmp` (default), `arp`.
- Default interface: `wlp0s20f3`.
- Mode and interface can be given in either order; anything that isn't a
  known mode name is treated as the interface.

This is for manual exploration only — it is not required to start or run a
lesson; the assistant drives capture experiments as part of each session.

## 6. Start the learning program

Tell the assistant:

```
resume lesson
```

The assistant will read the project documentation in order and pick up
exactly where the program left off — no other setup is needed.

Other student commands (see README.md's Student Commands table for full
detail):

| Command | What it does |
|---|---|
| `resume lesson` | Start a session: reads the docs, summarizes progress, states tonight's scope, asks one warm-up question. |
| `scope?` | Shows tonight's declared step list at any moment. |
| `go ahead` / `move on` | Skip the current question/discussion immediately. |
| `curiosity` | Short detour on a side question, then back to the roadmap. |
| `quiz me` | Conceptual quiz on what's been learned so far. |
| `end lesson for today` | Wraps up, archives the lesson, updates progress, commits and pushes. |
| `reset progress` | Wipes recorded progress and restarts the whole program from Version 1, archiving lesson history rather than deleting it. |

## 7. Repository layout

| File / directory | What it's for |
|---|---|
| `README.md` | Project philosophy and the Student Commands table. |
| `AGENTS.md` | Mentor rules the assistant follows (teaching order, pacing, evidence visibility, division of responsibility, commands). |
| `ROADMAP.md` | The 12-version curriculum and overall progress percentage. |
| `TASK.md` | The current milestone only — state, rewritten fresh each lesson. |
| `docs/handover.md` | Current state summary — rewritten fresh, never appended. |
| `docs/knowledge/` | Durable, deduplicated concept notes per protocol (cold reference). |
| `docs/lessons/` | Session-by-session history, one file per milestone (append-only within a milestone). |

For the full teaching philosophy and mentor rules, read `README.md` and
`AGENTS.md` directly — this guide only covers getting the repo running.
