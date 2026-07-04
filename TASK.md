# Current Task

## Version 3.0 — DNS fundamentals

**Objective:** Understand how names become IP addresses — the resolution
chain from an application's question to a DNS server's answer, observed as
real UDP packets on the student's machine.

History: Version 1 (ICMP) and Version 2 (ARP) are complete — see
`docs/lessons/`. Durable concepts: `docs/knowledge/icmp.md`,
`docs/knowledge/arp.md`. Lesson narrative for this milestone opens in
`docs/lessons/v3.0-dns.md`.

Hooks already earned in earlier lessons: ping sends nothing until the name
resolves (v2.0); the router doubles as the LAN's DNS server and answers
reverse lookups with DHCP-registered device names (v2.0, powers the viewer's
labels); friendly names in the ICMP viewer come from reverse DNS (v1.x).

---

## Immediate next steps

1. **Theory first (no code):** the resolution chain — application → stub
   resolver → configured DNS server (the router) → the world. Define: query/
   response, record types (A, PTR), UDP port 53, why DNS rides on UDP.
   Where the server address came from (DHCP, seen in v2.0).
2. **Observe the machine's resolver config:** `resolvectl status` (or
   `/etc/resolv.conf` and where it points) — who actually answers this
   machine's questions.
3. **Predict + capture a live DNS exchange:** `dig` a fresh name (and a
   reverse PTR lookup) while capturing UDP port 53. Assistant verifies the
   capture path first, independently. Prediction before each observation.
4. **Extend the viewer minimally** with a `dns` mode (capture filter +
   parser for query/response, showing name, type, answer) following the
   established mode pattern and the human-readable-labels rule.

## Tooling debt

- Viewer has `icmp` and `arp` modes only; `dns` mode needed for step 3–4.

---

## Definition of Done

The student can explain:

- The resolution chain: who asks whom, in what order, and where the DNS
  server address came from.
- What a DNS query and response look like on the wire (UDP 53, id matching,
  question/answer sections).
- A vs PTR lookups — forward and reverse resolution (already met PTR via the
  viewer's device names).
- Where caching happens and why repeated lookups don't hit the network.

---

## Teaching priority

Follow AGENTS.md **Pacing**, **Evidence Visibility**, and **Human-readable
output** rules: state scope at lesson start, one question per concept max,
quote any assistant-side evidence in-message, label unreadable values in
tool output, close the milestone the moment the DoD is met.
