"""Packet counters for the ICMP lesson."""

from dataclasses import dataclass

from packetlab.parser import IcmpPacket


@dataclass
class PacketStats:
    total: int = 0
    sent: int = 0
    received: int = 0
    echo_requests: int = 0
    echo_replies: int = 0
    other_icmp: int = 0
    unparsed_lines: int = 0
    last_unparsed: str = ""

    def observe(self, packet: IcmpPacket, my_ips: set[str]) -> None:
        self.total += 1

        if packet.source_ip in my_ips:
            self.sent += 1
        elif packet.destination_ip in my_ips:
            self.received += 1

        icmp_type = packet.icmp_type

        if icmp_type == "Echo Request":
            self.echo_requests += 1
        elif icmp_type == "Echo Reply":
            self.echo_replies += 1
        else:
            self.other_icmp += 1

    def observe_unparsed(self, line: str) -> None:
        self.unparsed_lines += 1
        self.last_unparsed = line

    @property
    def request_reply_gap(self) -> int:
        return self.echo_requests - self.echo_replies
