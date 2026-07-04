# ARP & Layer-2 Addressing — Durable Knowledge

Distilled, concept-organized reference. Timeless notes, not a session log.
Session narrative lives in `docs/lessons/v2.0-arp.md`.

---

## Two layers of addressing

- **IP** is logical: assigned by configuration (DHCP), hierarchical (prefix =
  network, rest = host), routable, and constant **end-to-end** for a packet's
  whole journey.
- **MAC** is physical: 48-bit identifier of a specific network card, flat (no
  hierarchy, so unroutable), meaningful only on the local link, and valid for
  **one hop**.
- Division of labour: IP gets the packet to the right network; MAC gets the
  frame across the final wire/radio hop. Neither can replace the other: NIC
  hardware filters only on MACs; routers can only aggregate hierarchical IPs.

## Frames and encapsulation

- A **frame** is the layer-2 envelope: src MAC + dst MAC wrapping the IP
  packet (which wraps ICMP/TCP/etc.).
- Every router **unwraps the arriving frame and builds a new one** (its own
  MAC as source, next hop's MAC as destination); the IP packet inside is the
  constant. Verified in capture: ping to 8.8.8.8 has dst MAC = router,
  dst IP = 8.8.8.8.

## ARP request/reply

- Request: "who-has <IP> tell <my IP>", sent to the broadcast MAC
  `ff:ff:ff:ff:ff:ff` — broadcast **by necessity**: you cannot unicast a
  question to the address you don't yet know. Every NIC accepts broadcast;
  non-owners discard, the owner replies.
- Reply: **unicast** straight back — "<IP> is-at <MAC>".
- Measured on this LAN: question to answer in ~8 ms.
- ARP resolves the **next hop from the routing decision, never the final
  destination** (for remote IPs the request asks for the router's MAC).

## Why ARP never crosses the router

- ARP is **not IP**: ethertype `0x0806`, no IP header, no TTL — nothing a
  router could route.
- Its destination is the broadcast MAC = "everyone on this segment", and
  routers do not forward broadcasts (a forwarded broadcast would flood
  networks without bound). LAN-scoped by design; "resolves only the next
  hop" is the same fact from the other side.

## The neighbour cache (`ip neigh`) and its states

- The kernel caches IP→MAC answers so it doesn't broadcast per packet.
  Populated **only by need** — devices actually framed packets to; there is
  no inventory of the LAN.
- States observed live: **REACHABLE** (recently confirmed, trusted) →
  ~30s idle → **STALE** (kept but unconfirmed; on next use the kernel
  re-verifies with a **unicast** probe to the remembered MAC) → back to
  REACHABLE, or **FAILED** (asked, nobody answered).
- The kernel broadcasts **only when it has no entry at all**. In an hour of
  capture the laptop broadcast exactly twice — once per forced
  `ip neigh del`. Everything else was unicast maintenance, in both
  directions (the router probes its entry for the laptop too).
- STALE is an engineered trade-off: broadcast-per-packet is always-correct
  but wasteful; trust-forever breaks when DHCP reassigns an IP (observed
  for real: phone reconnected as `.118` after holding `.152`). Use-but-verify
  accepts a few packets briefly lost to a dead MAC in exchange for a quiet
  LAN. General lesson: caches trade transient inconsistency for performance.
- A deleted entry can be re-created within milliseconds by background
  traffic — `ip neigh show` seconds later proves nothing about the deletion;
  the broadcast on the radio is the proof. `ip monitor neigh` streams state
  transitions live.
- ARP replies are unauthenticated — any device may claim any IP ("ARP
  spoofing"). A trade-off inherited from trusted-LAN-era design.

## DHCP leases and device names (Version 3 preview, observed facts)

- The router's DHCP server keys leases by MAC; a reconnecting device usually
  gets its old IP back while the lease lives, but not always (observed:
  `.152` → `.118`).
- Devices register a hostname with their DHCP request; the router doubles as
  the LAN's DNS server and answers reverse lookups with those names
  (`192.168.8.118` → `Udara-s-S24-Ultra`). This is where the viewer's device
  names come from — resolved live, never hardcoded.

## Ambient LAN chatter (observed, to explore later)

- The LAN is never silent: captures show neighbours broadcasting who-has
  queries continuously and the router probing its own cache entries. A
  Wi-Fi capture in ordinary (managed) mode sees broadcasts plus its own
  unicast traffic — unicast between two *other* devices does not appear.

---

## Tooling / architecture facts worth keeping

- Viewer modes: `packetlab.py [icmp|arp] [interface]` — mode and interface
  args accepted in any order; `icmp` is the default.
- ARP mode captures with `-e` because frame (MAC) headers are the story.
- **Self-describing instrument**: the stats panel shows the exact tcpdump
  command being run (`Running :`). The tool must never be a black box.
- **Human-readable labels beside raw values** (standing rule, AGENTS.md):
  `(me)` from `/sys/class/net/<iface>/address`, `(router)` from
  `ip route show default`, device IP/names from `ip neigh` + reverse DNS.
  Raw value never replaced; labels never hardcoded.
- Bug lesson 3 — phantom "unparsed" packet: tcpdump emits a blank stdout
  line while shutting down; counting it as unparsed made a clean capture
  look like a parser mismatch. Blank lines are dropped at the capture layer
  (`iter_lines`). General lesson: sanitize subprocess stream edges where the
  stream is produced, not in every consumer.
