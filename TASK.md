# Current Task

## Version 1.2 — loopback ICMP

**Objective:** Explain why ICMP traffic to `127.0.0.1` appears on `lo` and never
on the Wi-Fi interface (`wlp0s20f3`). This is a Linux networking milestone, not a
software-architecture one.

History: see `docs/lessons/v1.1-icmp-fundamentals.md` and
`docs/lessons/v1.2-loopback.md`. Durable concepts: `docs/knowledge/icmp.md`.

---

## Immediate next steps

1. **Confirm `setcap`.** Verify the student ran
   `sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/tcpdump`. Check with
   `getcap /usr/bin/tcpdump`. Once confirmed, the assistant can run captures
   itself (no sudo) for independent verification. See "Non-root capture via
   `setcap`" in `docs/knowledge/icmp.md`.
2. **Real `127.0.0.1` test on `wlp0s20f3` (NOT YET RUN).** Capture on
   `wlp0s20f3` while running an actual `ping -c 3 127.0.0.1`; confirm zero
   packets appear. The earlier `wlp0s20f3` screenshot was a router ping, so this
   prediction has never been directly tested.
3. **Re-run the `lo` capture and read sent/received.** Run
   `python3 scripts/packetlab.py lo` with `ping -c 3 127.0.0.1` now that the
   `my_ips` fix (BUG 2) is in, and look at "Sent by me" / "Received by me". That
   fix has not been live-verified yet.
4. **Explain destination-route interface selection.** Get the student's own
   synthesis of why Linux keeps `127.0.0.1` traffic inside `lo` instead of
   sending it out the Wi-Fi NIC (routing decision is by destination address).
5. **Discuss sent-vs-received for self-addressed traffic.** Because loopback
   source == destination == `127.0.0.1`, every loopback packet now counts as
   "sent" and none as "received". Not a bug to patch — a genuine consequence.

---

## Open conceptual questions (blocking Definition of Done)

- Why does traffic to `127.0.0.1` stay inside `lo` instead of leaving via Wi-Fi?
  (Student's final synthesis has not happened yet.)
- What do "sent" and "received" even mean when a machine pings itself and source
  and destination are the same address?

---

## Definition of Done

The student can explain:

- What `lo` is and why `127.0.0.1` is special.
- Why localhost packets never leave the machine.
- Why capturing on `wlp0s20f3` shows no localhost ping traffic (still needs the
  real direct test — step 2).
- Why capturing on `lo` shows the localhost ICMP request/reply pairs.
  (Observed: 12 packets / 6 requests / 6 replies / 0 unparsed.)
- How Linux chooses an outgoing interface from the destination route.
- What "sent" vs "received" means for self-addressed traffic.

---

## Teaching priority

Experiments, not refactoring. Do not teach repository architecture unless the
tool output itself becomes confusing. Do not move to ARP until this milestone is
understood. (Roadmap: `ROADMAP.md`. Mentor style + standing directives:
`AGENTS.md`.)
