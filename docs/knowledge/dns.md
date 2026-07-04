# DNS — Durable Knowledge

Distilled, concept-organized reference. Timeless notes, not a session log.
Session narrative lives in `docs/lessons/v3.0-dns.md`. (Milestone in
progress — this file grows as understanding lands.)

---

## Configuration vs cache — two kinds of DNS knowledge

- **Configuration** answers "who do I ask?": the DNS server's IP address,
  delivered by DHCP when joining the network, valid for the lease. It holds
  zero answers — it is an address-book entry for the answerer. A machine
  never has to *discover* its DNS server by broadcast; it was told.
- **Cache** holds "answers I've been given": name→IP results, each with a
  TTL. Starts empty, fills per query, entries expire on their own.

## The resolution chain (as observed on this machine)

```
application
   → 127.0.0.53  systemd-resolved stub, reached via lo (never the radio);
                 answers from its cache when it can
   → 192.168.8.1 the router, configured per-link by DHCP (wlp0s20f3);
                 a real UDP packet with all a packet's needs (ARP, frame)
   → upstream / authoritative servers
```

- `/etc/resolv.conf` on Ubuntu points every application at the local stub
  (`nameserver 127.0.0.53`, "resolv.conf mode: stub").
- `resolvectl status` shows the per-link upstream servers. DNS servers are
  per-interface because different networks bring different servers (DHCP
  here, a VPN's server there).
- Caching happens at **every** level (stub, router, upstream) — only the
  first lookup of a name hits the network; a cache hit at the stub keeps the
  radio completely silent (loopback only).

## Order of operations: ARP → DNS → ICMP/anything

With empty caches, nothing can leave before ARP (even the DNS query is just
a UDP packet needing a frame with the router's MAC), and no packet to a
named destination can exist before DNS supplies its IP. Each step
manufactures the address the next step's envelope requires. One ARP
exchange serves everything after it.

## Protocol shape

- DNS is application-layer, riding **UDP port 53**. Why UDP: one tiny
  question, one tiny answer; TCP's handshake would triple the traffic for a
  single-datagram exchange. Loss is handled by re-asking. (Large answers
  have a fallback path.)
- Every query carries an **ID**; the response echoes it so answers pair with
  questions — the same pairing trick as ICMP's id/seq.
- Record types met so far: **A** = name → IPv4 (forward); **PTR** = IP →
  name (reverse — the query behind the viewer's device-name labels, answered
  by the router from DHCP-registered hostnames).
