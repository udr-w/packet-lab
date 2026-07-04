"""Parse tcpdump text into small Python objects."""

from dataclasses import dataclass
import re


TCPDUMP_ICMP_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) "
    r"(\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"IP\s+([\d.]+)\s+>\s+([\d.]+):\s+"
    r"ICMP\s+(.+)$"
)


@dataclass(frozen=True)
class IcmpPacket:
    """One ICMP packet decoded from a tcpdump output line."""

    raw: str
    date: str
    time: str
    source_ip: str
    destination_ip: str
    message: str

    @property
    def short_time(self) -> str:
        return self.time[:12]

    @property
    def icmp_type(self) -> str:
        lowered = self.message.lower()

        if "echo request" in lowered:
            return "Echo Request"
        if "echo reply" in lowered:
            return "Echo Reply"

        return self.message.strip()


BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"

# With -e, tcpdump prints the frame header before the ARP message:
# 2026-07-04 13:21:04.568484 d4:54:8b:6a:1a:99 > ff:ff:ff:ff:ff:ff, \
#   ethertype ARP (0x0806), length 42: Request who-has 192.168.8.1 \
#   tell 192.168.8.173, length 28
TCPDUMP_ARP_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) "
    r"(\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})\s+>\s+"
    r"([0-9a-f]{2}(?::[0-9a-f]{2}){5}),\s+"
    r"ethertype ARP \(0x0806\),\s+length \d+:\s+"
    r"(Request|Reply)\s+(.+?)(?:,\s+length\s+\d+)?$"
)


@dataclass(frozen=True)
class ArpPacket:
    """One ARP packet decoded from a tcpdump -e output line."""

    raw: str
    date: str
    time: str
    source_mac: str
    destination_mac: str
    operation: str  # "Request" or "Reply"
    detail: str  # e.g. "who-has 192.168.8.1 tell 192.168.8.173"

    @property
    def short_time(self) -> str:
        return self.time[:12]

    @property
    def is_broadcast(self) -> bool:
        return self.destination_mac == BROADCAST_MAC


def parse_arp_line(line: str) -> ArpPacket | None:
    """Parse one tcpdump -e line, returning None when it is not our ARP shape."""
    match = TCPDUMP_ARP_PATTERN.match(line)

    if not match:
        return None

    date, time, source_mac, destination_mac, operation, detail = match.groups()

    return ArpPacket(
        raw=line,
        date=date,
        time=time,
        source_mac=source_mac,
        destination_mac=destination_mac,
        operation=operation,
        detail=detail.strip(),
    )


def parse_tcpdump_line(line: str) -> IcmpPacket | None:
    """Parse one tcpdump line, returning None when it is not our ICMP shape."""
    match = TCPDUMP_ICMP_PATTERN.match(line)

    if not match:
        return None

    date, time, source_ip, destination_ip, message = match.groups()

    return IcmpPacket(
        raw=line,
        date=date,
        time=time,
        source_ip=source_ip,
        destination_ip=destination_ip,
        message=message.strip(),
    )

