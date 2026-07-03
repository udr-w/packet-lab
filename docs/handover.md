# Packet Lab — Handover

The "resume here" pointer. State only — rewritten fresh each lesson, not a log.
For the roadmap see `ROADMAP.md`; for mentor style and standing directives see
`AGENTS.md`.

---

## Student profile

- BSc holder, 3+ years as a senior software engineer. Ubuntu user, comfortable
  with Python and the Linux terminal.
- Prefers learning by building tools over using GUI applications; uses AI tools in
  terminal, not the web UIs or IDEs like VS Code.
- Software-engineering fundamentals (functions, modules, general programming) do
  NOT need explaining — keep depth and pace on networking/OS concepts.
- Prefers theory-before-prediction, jargon-defined-first teaching ("easier,
  closer and practical").
- **Pacing is critical**: lessons often run late at night; the student has zero
  tolerance for padding, repeat check questions, or reopened design debates.
  Follow the AGENTS.md "Pacing" rules strictly.
- **Never reads, edits, or debugs repository files.** That is entirely the
  assistant's job, including preparing/fixing tooling before asking the student
  to run anything. The student runs commands, observes, and answers conceptual
  questions.

Project location: `~/Documents/Scripts/packet-lab`

---

## Overall goal

Build our own terminal-based network analyzer from scratch (tcpdump for capture,
Python for parsing/presentation, Rich/Textual for the UI). The point is not to
replace Wireshark but to understand every networking concept by implementing it
ourselves — one protocol at a time, fully, before moving on.

---

## Current state

- **Version 1 (ICMP) is COMPLETE** — v1.2 loopback closed 2026-07-04 with all
  Definition-of-Done items met (wlp0s20f3 zero-packet test run for real,
  routing synthesis given by the student, sent/received semantics decided:
  counters stay as-is, do not reopen).
- **Next milestone: Version 2.0 — ARP.** Not started; scope, steps, and
  Definition of Done are in `TASK.md`. Open `docs/lessons/v2.0-arp.md` at the
  start of that lesson.
- **Capture access: RESOLVED.** `setcap` on tcpdump is confirmed applied and
  live-verified — both the assistant and the student run captures without sudo.
  The assistant now independently verifies every capture experiment itself.
- **Tooling status:** viewer healthy; three bugs found and fixed across v1.2
  (hidden tcpdump stderr; `127.0.0.1` missing from `my_ips`; packet table
  cropped/vanishing — now evidence-first, height-adaptive, and reprinted after
  Ctrl+C). Known debt: capture filter and parser are ICMP-only; ARP mode is
  needed for v2.0 (tracked in `TASK.md`).

---

## Where things live

- `TASK.md` — current milestone only: next steps, open questions, Definition of
  Done. State, rewritten each lesson.
- `docs/knowledge/` — durable, concept-organized understanding (cold reference,
  no session narrative). Current file: `docs/knowledge/icmp.md`.
- `docs/lessons/` — cold archive, one file per milestone; the session narrative,
  predictions/observations, and bug-fix records live here:
  `docs/lessons/v1.1-icmp-fundamentals.md` (closed),
  `docs/lessons/v1.2-loopback.md` (in progress).
- `scripts/lab-doctor.py` — documentation health monitor; enforces per-file size
  caps and flags anti-patterns (unbounded logs, "Completed" sections in
  TASK.md). Run `python3 scripts/lab-doctor.py` before each lesson.
- **Version control:** the lab is its own git repo (branch `main`), pushed to the
  private GitHub repo `github.com/udr-w/packet-lab`. `end lesson for today`
  auto-commits and pushes after lab-doctor passes. Packet captures are gitignored
  (`capture/`, `*.pcap`/`*.pcapng`/`*.cap`) — they may contain sensitive traffic
  and must never be committed.
