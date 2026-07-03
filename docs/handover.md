# Packet Lab — Handover

The "resume here" pointer. State only — rewritten fresh each lesson, not a log.
For the roadmap see `ROADMAP.md`; for mentor style and standing directives see
`AGENTS.md`.

---

## Student profile

- BSc holder, 3+ years as a senior software engineer. Ubuntu user, comfortable
  with Python and the Linux terminal.
- Prefers learning by building tools over using GUI applications; uses Codex in
  VS Code / terminal, not the ChatGPT web UI.
- Software-engineering fundamentals (functions, modules, general programming) do
  NOT need explaining — keep depth and pace on networking/OS concepts.
- Prefers theory-before-prediction, jargon-defined-first teaching ("easier,
  closer and practical").
- **Never reads, edits, or debugs repository files.** That is entirely the
  assistant's job, including preparing/fixing tooling before asking the student
  to run anything. The student runs commands, observes, and answers conceptual
  questions.

Project location: `/home/enactor/Documents/Scripts/packet-lab`

---

## Overall goal

Build our own terminal-based network analyzer from scratch (tcpdump for capture,
Python for parsing/presentation, Rich/Textual for the UI). The point is not to
replace Wireshark but to understand every networking concept by implementing it
ourselves — one protocol at a time, fully, before moving on.

---

## Current state

- **Milestone: Version 1.2 — loopback ICMP, mid-flight.** The immediate steps,
  open questions, and Definition of Done live in `TASK.md`.
- Confirmed so far: pinging `127.0.0.1` while capturing on `lo` yields 12 packets
  / 6 Echo Requests / 6 Echo Replies / 0 unparsed. Still open: the direct
  `wlp0s20f3` + `127.0.0.1` zero-packet test, the sent/received re-read, and the
  student's own explanation of destination-route interface selection.
- **Tooling status:**
  - BUG 1 (tcpdump stderr hidden behind Rich's alternate screen) — fixed in
    `packetlab/capture.py` + `scripts/packetlab.py`.
  - BUG 2 (`127.0.0.1` missing from the resolver's `my_ips`) — fixed in
    `packetlab/resolver.py`; not yet live-verified.
  - The hard root requirement (`os.geteuid() == 0`) was removed from
    `scripts/packetlab.py`. Non-root capture now relies on `setcap` on the
    tcpdump binary — **the student has NOT yet confirmed running the setcap
    command**, so the assistant still cannot capture independently.
  - The assistant does NOT have passwordless sudo on this machine; the student
    must run anything needing root until setcap is confirmed.

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
