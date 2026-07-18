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

- **Version 3.0 (DNS) is IN PROGRESS** — session 1 done 2026-07-04: theory
  (chain, UDP 53, A/PTR, configuration-vs-cache) and resolver config
  observed (127.0.0.53 stub → per-link 192.168.8.1). Remaining: the
  unanswered configuration-vs-cache warm-up, the live dig×2 capture proving
  the banked cache prediction, a PTR lookup, and the `dns` viewer mode.
  Plan in `TASK.md`; narrative in `docs/lessons/v3.0-dns.md`. Exact session
  position comes from `./packet-lab.sh resume`, never from this file.
- **Versions 1 (ICMP) and 2 (ARP) are COMPLETE** (both closed 2026-07-04).
  Durable concepts: `docs/knowledge/icmp.md`, `arp.md`, `dns.md` (growing).
- **Tooling status:** viewer healthy with `icmp` and `arp` modes
  (`python3 scripts/packetlab.py [mode] [interface]`). ARP mode shows frame
  MACs (`-e`), labels every MAC/IP beside the raw value (me / router /
  broadcast / device names via reverse DNS — nothing hardcoded), and the
  stats panel displays the exact tcpdump command running. Known debt: `dns`
  mode needed for v3.0 (tracked in `TASK.md`).
- **Standing directives in AGENTS.md (all born 2026-07-04):** "Evidence
  Visibility", "Human-readable output", "Question quality" (questions must
  state givens completely, using only already-taught distinctions), and the
  Pacing rules — read all before teaching. The end-lesson wrap-up must end
  with the ROADMAP.md progress percentage as its final line.
- **Control plane + multi-learner foundation: MERGED into `main`** (PR #1,
  CI green, 2026-07-18). A deterministic control plane lives in `packetlab/lab/`,
  driven by `python3 -m packetlab.lab ...` (or `./packet-lab.sh`): the Curriculum
  Governor (lesson state machine, scope, budgets), the concept-level learner
  model, the restricted runner, the generated-tool lifecycle, hash-chained run
  traces, and **per-learner isolation** (each engineer has an isolated profile
  under `state/learners/<id>/`; the active learner shows in every command and
  trace). Health: `python3 -m packetlab.lab doctor`; tests
  (`./packet-lab.sh test`, 161) and evals (`./packet-lab.sh eval`, 54) pass. See
  AGENTS.md ("Curriculum Governor" + "Multi-learner context isolation") and
  `docs/architecture.md`. This did NOT change lesson progress — DNS (v3.0) is
  still where it was.
- **Next phase = real learner usage, not more architecture.** The agentic
  control plane and multi-learner foundation are complete and merged; the
  architecture work is done for now. The next step is running actual lessons
  through it (start with `learner create <id>`, then resume the v3.0 DNS lesson
  per TASK.md). Optional roadmap items (shared tool registry, profile renaming,
  namespace isolation, separate-model grader) are deferred, not pending — do not
  build them speculatively; let real lesson usage drive what's needed next.
- **Fast resume (2026-07-18):** session resume now starts with ONE read-only
  call — `./packet-lab.sh resume --json` — per the Fast Resume Protocol
  (AGENTS.md Operating Modes; `.claude/skills/resume-lesson/SKILL.md`;
  `docs/fast-resume.md`). No doctor/tests/doc sweep at resume; private
  preflight only when the snapshot recommends it, using its disposable
  target, never shown to the learner.
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
  private GitHub repo `github.com/udr-w/packet-lab`. Commits and pushes are
  proportional to durable value (`lesson end` prints the policy): a no-op
  session touches nothing, evidence commits locally, only milestones and
  engineering work push. Packet captures and `state/` (learner-private) are
  gitignored and must never be committed.
