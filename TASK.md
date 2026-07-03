# Current Task

## Version 2.0 — ARP fundamentals

**Objective:** Understand how devices discover each other's MAC addresses on a
LAN — why IP addresses alone are not enough to deliver a packet on the local
network, and how ARP (Address Resolution Protocol) fills the gap.

History: Version 1 (ICMP) is complete — see `docs/lessons/v1.1-*.md`,
`docs/lessons/v1.2-*.md`. Durable concepts: `docs/knowledge/icmp.md`.
Lesson narrative for this milestone opens in `docs/lessons/v2.0-arp.md`.

---

## Immediate next steps

1. **Theory first (no code):** two address layers — IP (logical, routed) vs MAC
   (physical, LAN-local). Why the kernel needs a MAC to actually transmit a
   frame to the router or a LAN neighbor. Define frame, broadcast,
   request/reply shape of ARP.
2. **Observe the ARP cache:** `ip neigh` — the kernel's IP→MAC table on the
   student's machine. Relate entries to known devices (router `192.168.8.1`).
3. **Predict + capture a live ARP exchange:** flush or age out an entry, ping
   the router, capture `arp` traffic with tcpdump (assistant verifies first,
   independently). Note: ARP is NOT carried in IP — the current viewer's
   `icmp` filter and IP-based parser will not see it.
4. **Extend the tool minimally** so ARP packets can be observed (capture filter
   + a small ARP parser). Only enough tooling to make the observation easier.

## Tooling debt (do before/while step 3)

- `packetlab` currently hard-codes the `icmp` tcpdump filter and an ICMP-only
  parser. Needs an `arp` mode for this milestone.

---

## Definition of Done

The student can explain:

- Why a machine with the destination IP still needs a MAC address to deliver on
  the LAN (two-layer addressing).
- What an ARP request/reply looks like and why the request is a broadcast.
- What the ARP cache (`ip neigh`) is for and what its entry states mean.
- Why ARP never crosses the router (LAN-scoped, not routed).

---

## Teaching priority

Follow the new AGENTS.md **Pacing** rules: state scope at lesson start, one
question per concept max, close the milestone the moment the Definition of Done
is met. Experiments over refactoring. (Roadmap: `ROADMAP.md`.)
