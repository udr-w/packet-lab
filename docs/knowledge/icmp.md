# ICMP & Loopback — Durable Knowledge

Distilled, concept-organized reference for what is understood about ICMP, the
loopback interface, and the surrounding Linux/tooling facts. Timeless notes, not
a session log. Session narrative lives in `docs/lessons/`; current work lives in
`TASK.md`.

---

## ICMP request/reply model

- `ping` works by sending ICMP **Echo Request** packets and expecting ICMP
  **Echo Reply** packets in return.
- Each ping produces a **request/reply pair**: one Echo Request out, one Echo
  Reply back. `ping -c 3 <host>` therefore yields 3 requests + 3 replies = 6
  packets total, with a request/reply gap of 0 when nothing is lost.
- The direction is always: the initiator sends the Echo Request; the target
  answers with the Echo Reply. When the phone pings the laptop, the phone sends
  the request and the laptop sends the reply; when the laptop pings the phone,
  the roles flip.

## ICMP rides directly on IP (no TCP)

- ICMP is carried **directly inside IP**. It does not use TCP or UDP and has no
  ports or connection handshake — it sits alongside TCP/UDP as its own
  IP-layer protocol.

## Packet direction comes from source/destination IP

- The **source and destination IP addresses are the ground truth** for who sent
  a packet and where it is going. Everything else the viewer prints (friendly
  names, "sent by me / received by me" labels, request/reply classification) is
  **interpretation layered on top of that evidence**, not the evidence itself.
- Friendly host names are derived from the IP via reverse DNS; they are a
  convenience, not a source of truth.

## Local next hop vs. remote destination

- Pinging a **remote host** (e.g. `google.com`, resolving to something like
  `cm-in-f100.1e100.net`) and pinging the **local router** both follow the
  identical ICMP request/reply pattern at the packet level.
- The distinction is topological, not protocol-level: the router is the local
  next hop, while a remote IP is reached *through* that next hop. The ICMP
  exchange looks the same regardless.

## The loopback interface (`lo`) and `127.0.0.0/8`

- `lo` is a **virtual interface with no physical hardware**. It exists purely in
  software and carries traffic addressed to the machine itself.
- The whole `127.0.0.0/8` range is loopback; `127.0.0.1` (`localhost`) is the
  canonical address.

## Why localhost traffic never hits the wire (destination-route interface selection)

- Linux chooses an outgoing interface **based on the destination address and the
  routing table**, not based on which interface a tool is "watching."
- Traffic to `127.0.0.1` matches the loopback route, so the kernel keeps it
  entirely inside `lo`. It never reaches a physical NIC.
- Consequence, confirmed by capture: pinging `127.0.0.1` produces **no packets**
  on `wlp0s20f3` (the Wi-Fi interface) but **does** produce the full ICMP
  request/reply exchange on `lo`. Two `ping -c 3 127.0.0.1` runs captured on `lo`
  gave 12 packets: 6 Echo Requests, 6 Echo Replies, 0 unparsed lines.

## "Sent" vs "received" semantics break down for self-addressed traffic

- The viewer classifies a packet as "sent by me" if its source is one of the
  machine's own IPs, else "received by me" if its destination is. This works for
  normal traffic where source and destination differ.
- For **loopback traffic the source and destination are both `127.0.0.1`** — the
  machine is talking to itself. Both endpoints are "me," so the "sent vs
  received" distinction has no clean answer.
- With a simple `if source in my_ips: sent += 1; elif dest in my_ips: received
  += 1` scheme, every loopback packet (requests *and* replies) falls into the
  first branch and counts as **sent**, leaving received at 0. This is not a bug
  to patch away — it is a genuine, informative consequence of self-addressed
  traffic and a real limitation of a source/destination-based direction model.

---

## Tooling / architecture facts worth keeping

### Raw line beside parsed fields
- `IcmpPacket` retains the original tcpdump line in `packet.raw`; parsed fields
  are added **beside** the raw data, never replacing it. This lets our
  interpretation be compared directly against the real Linux capture output, and
  means information is never discarded.
- The viewer also displays **unparsed tcpdump lines** rather than dropping them,
  so a parser mismatch is visible instead of silently producing an empty table.

### Module layout
- `packetlab/capture.py` starts tcpdump and yields raw output lines;
  `parser.py` turns tcpdump text into `IcmpPacket` objects; `resolver.py`
  identifies local IPs and does reverse DNS; `stats.py` counts totals and
  request/reply pairs; `ui.py` renders the Rich table and stats panels;
  `scripts/packetlab.py` is the CLI entry point.
- The viewer runs `tcpdump -i <interface> -nn -tttt -l icmp`.

### Bug lesson 1 — hidden tcpdump stderr behind Rich's alternate screen
- Rich `Live` with `screen=True` switches to the terminal's **alternate screen
  buffer**. If tcpdump's stderr is inherited by the terminal, any startup
  message or fatal error is shown for a fraction of a second and then covered by
  the alternate screen. A **failed capture then looks identical to "no traffic
  captured."**
- Durable fix: capture.py **pipes** tcpdump's stderr rather than inheriting it,
  and the entry point reports tcpdump's exit code and any stderr once the
  capture ends (unless the user stopped it with Ctrl+C). General lesson: never
  let a child process's error output get swallowed by a full-screen TUI; surface
  exit status explicitly.

### Bug lesson 2 — `127.0.0.1` missing from `my_ips`
- `HostResolver._get_my_ips()` built its set from `hostname -I`, which lists only
  real NIC addresses and **never includes `127.0.0.1`**. So loopback ICMP
  (source == destination == `127.0.0.1`) matched neither branch of the sent/
  received counter, showing 0 sent and 0 received despite real packets.
- Fix: `resolver.py` always adds `127.0.0.1` to `my_ips`. General lesson:
  the machine's own address set is more than what `hostname -I` reports —
  loopback addresses must be added explicitly.

### Non-root capture via `setcap`
- tcpdump can capture without root by granting the binary the Linux
  capabilities it needs, the same technique Wireshark's `dumpcap` uses:
  ```bash
  sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/tcpdump
  ```
  This scopes elevated privilege to that single binary only — no standing root,
  no `sudoers`/NOPASSWD change, no shared password.
- Because this removes the need to run under `sudo`, the viewer no longer hard-
  requires `os.geteuid() == 0`. It also incidentally avoids the old
  `ModuleNotFoundError: No module named 'rich'` problem, which was caused by
  `sudo python3` using a **different package environment** than the normal user
  (fix if ever running under sudo again: `sudo apt install python3-rich`).
- **Caveat:** `apt upgrade` replacing the tcpdump binary **resets** the
  capability. Verify with `getcap /usr/bin/tcpdump`; if empty, re-apply.
