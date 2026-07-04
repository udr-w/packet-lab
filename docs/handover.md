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
- **Evidence visibility is critical** (directive born 2026-07-04): the student
  sees only the assistant's messages and their own terminal. Quote any
  assistant-side command + raw output in-message; never imply the student
  should have known invisible results. Follow AGENTS.md "Evidence Visibility".
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

- **Version 2.0 (ARP) is COMPLETE** — closed 2026-07-04, all Definition-of-Done
  items met in one session (two-layer addressing, broadcast/unicast shape,
  neighbour cache states probed live, LAN-scoping explained). Narrative:
  `docs/lessons/v2.0-arp.md`; durable concepts: `docs/knowledge/arp.md`.
  Version 1 (ICMP) closed earlier the same day.
- **Next milestone: Version 3.0 — DNS.** Not started; scope, steps, and
  Definition of Done are in `TASK.md`. Open `docs/lessons/v3.0-dns.md` at the
  start of that lesson.
- **Tooling status:** viewer healthy with `icmp` and `arp` modes
  (`python3 scripts/packetlab.py [mode] [interface]`). ARP mode shows frame
  MACs (`-e`), labels every MAC/IP beside the raw value (me / router /
  broadcast / device names via reverse DNS — nothing hardcoded), and the
  stats panel displays the exact tcpdump command running. Known debt: `dns`
  mode needed for v3.0 (tracked in `TASK.md`).
- **New standing directives in AGENTS.md (2026-07-04):** "Evidence
  Visibility" and "Human-readable output" — read both before teaching.
- **Capture access: RESOLVED.** `setcap` on tcpdump confirmed applied; both
  assistant and student capture without sudo. Caveat: an apt upgrade of
  tcpdump resets it — check `getcap /usr/bin/tcpdump` if capture fails.
- **Useful machine facts:** laptop `192.168.8.173` / `d4:54:8b:6a:1a:99` on
  `wlp0s20f3`; router `192.168.8.1` / `98:a9:42:13:87:32`; router serves DNS
  and registers DHCP hostnames (phone resolves as `Udara-s-S24-Ultra`).
  These are observed values, not constants — always re-derive live.

---

## Where things live

- `TASK.md` — current milestone only: next steps, open questions, Definition of
  Done. State, rewritten each lesson.
- `docs/knowledge/` — durable, concept-organized understanding (cold reference,
  no session narrative). Files: `icmp.md`, `arp.md`.
- `docs/lessons/` — cold archive, one file per milestone; the session narrative,
  predictions/observations, and bug-fix records live here (`v1.1`, `v1.2`,
  `v2.0` closed).
- `scripts/lab-doctor.py` — documentation health monitor; enforces per-file size
  caps and flags anti-patterns. Run `python3 scripts/lab-doctor.py` before each
  lesson.
- **Version control:** the lab is its own git repo (branch `main`), pushed to the
  private GitHub repo `github.com/udr-w/packet-lab`. `end lesson for today`
  auto-commits and pushes after lab-doctor passes. Packet captures are gitignored
  (`capture/`, `*.pcap`/`*.pcapng`/`*.cap`) — they may contain sensitive traffic
  and must never be committed.
