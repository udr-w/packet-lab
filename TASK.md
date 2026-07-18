# Current Task

## Version 3.0 — DNS fundamentals (in progress)

**Objective:** Understand how names become IP addresses — the resolution
chain from an application's question to a DNS server's answer, observed as
real UDP packets on the student's machine.

Done so far (session 1, 2026-07-04): theory (chain, UDP 53, A/PTR, query
IDs, configuration-vs-cache distinction) and resolver config observed
(`127.0.0.53` stub → per-link `192.168.8.1`). Correct student predictions
banked: ARP → DNS → ICMP ordering; first-dig-on-radio / second-dig-silent.
Session 2 (2026-07-18) opened via the control plane, verified the capture
path, then ended early (student urgent task) — no new evidence recorded.
Narrative: `docs/lessons/v3.0-dns.md`. Durable notes so far:
`docs/knowledge/dns.md`.

---

## Immediate next steps

1. **Re-ask the warm-up** (posed 2026-07-18, unanswered): fresh network,
   DHCP done, nothing looked up yet — does the machine know any *answers*,
   and does it know *who to ask*? (configuration vs cache).
2. **Live capture:** student runs `dig` twice for a fresh name while
   capturing UDP port 53 on `wlp0s20f3` — confirm the banked prediction:
   query+response on the radio for dig #1 (stub cache miss, forwarded to
   `192.168.8.1`), radio silence for dig #2 (stub cache hit via `lo`).
   Capture path already verified 2026-07-18 (`getcap` intact; live query/
   response captured) — re-verify quickly at session start.
3. **Reverse lookup:** `dig -x` a LAN IP (PTR) — see the viewer's
   device-name mechanism as raw packets.
4. **Read the wire shape:** query ID matching, question/answer sections,
   the answer's TTL (= how long the caches may keep it).
5. **Extend the viewer** with a minimal `dns` mode (UDP 53 filter + parser
   showing name, record type, answer), following the established mode
   pattern, Evidence Visibility, and Human-readable output rules.

## Tooling debt

- Viewer has `icmp` and `arp` modes only; `dns` mode needed for step 5.

## Control plane

Start the session with `python3 -m packetlab.lab lesson start v3.0`
(learner `udara`), record evidence via `lab record`, close with
`lab lesson close --confirm "<criterion>"`. Session 2's run was aborted
cleanly with a reason — no dangling state.

---

## Definition of Done

The student can explain:

- The resolution chain: who asks whom, in what order, and where the DNS
  server address came from.
- What a DNS query and response look like on the wire (UDP 53, id matching,
  question/answer sections).
- A vs PTR lookups — forward and reverse resolution.
- Where caching happens and why repeated lookups don't hit the network
  (theory done — needs the live capture proof).

---

## Teaching priority

Follow AGENTS.md **Pacing**, **Evidence Visibility**, **Human-readable
output**, and **Question quality** rules: state scope at lesson start, one
question per concept max with givens stated completely, quote assistant-side
evidence in-message, label unreadable values, close the milestone the moment
the DoD is met.
