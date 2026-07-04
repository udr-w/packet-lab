# Current Task

## Version 3.0 — DNS fundamentals (in progress)

**Objective:** Understand how names become IP addresses — the resolution
chain from an application's question to a DNS server's answer, observed as
real UDP packets on the student's machine.

Done so far (session 1, 2026-07-04): theory (chain, UDP 53, A/PTR, query
IDs, configuration-vs-cache distinction) and resolver config observed
(`127.0.0.53` stub → per-link `192.168.8.1`). Correct student predictions
banked: ARP → DNS → ICMP ordering; first-dig-on-radio / second-dig-silent.
Narrative: `docs/lessons/v3.0-dns.md`. Durable notes so far:
`docs/knowledge/dns.md`.

---

## Immediate next steps

1. **Live capture (opens next session):** student runs `dig` twice for a
   fresh name while capturing UDP port 53 on `wlp0s20f3` — confirm the
   banked prediction: query+response on the radio for dig #1 (stub cache
   miss, forwarded to `192.168.8.1`), radio silence for dig #2 (stub cache
   hit via `lo`). Assistant verifies the capture path first and quotes the
   exact command + raw output in-message.
2. **Reverse lookup:** `dig -x` a LAN IP (PTR) — see the viewer's
   device-name mechanism as raw packets.
3. **Read the wire shape:** query ID matching, question/answer sections,
   the answer's TTL (= how long the caches may keep it).
4. **Extend the viewer** with a minimal `dns` mode (UDP 53 filter + parser
   showing name, record type, answer), following the established mode
   pattern, Evidence Visibility, and Human-readable output rules.

## Tooling debt

- Viewer has `icmp` and `arp` modes only; `dns` mode needed for step 4.

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
