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

