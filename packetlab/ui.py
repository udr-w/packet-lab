"""Rich terminal rendering for the packet viewer."""

from datetime import datetime

from rich.console import Group
from rich.panel import Panel
from rich.table import Table

from packetlab.parser import IcmpPacket
from packetlab.resolver import HostResolver
from packetlab.stats import PacketStats


DEFAULT_MAX_ROWS = 20

# Terminal lines consumed by everything that is not a packet row:
# the stats panel (12-13 text lines + 2 border lines) and the table's
# own title, header, and border lines.
STATS_PANEL_LINES = 15
TABLE_CHROME_LINES = 5


def row_budget(terminal_height: int) -> int:
    """How many packet rows fit on screen alongside the stats panel."""
    return max(3, terminal_height - STATS_PANEL_LINES - TABLE_CHROME_LINES)


def packet_row(packet: IcmpPacket, resolver: HostResolver) -> tuple[str, ...]:
    return (
        packet.short_time,
        resolver.resolve(packet.source_ip),
        resolver.resolve(packet.destination_ip),
        "ICMP",
        packet.icmp_type,
    )


def build_packet_table(
    packets: list[IcmpPacket],
    resolver: HostResolver,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Table:
    table = Table(title="ICMP Packets", expand=True)
    table.add_column("Time", style="cyan", no_wrap=True)
    table.add_column("Source", style="green")
    table.add_column("Destination", style="green")
    table.add_column("Protocol", style="magenta", no_wrap=True)
    table.add_column("Message", style="yellow")

    for packet in packets[-max_rows:]:
        table.add_row(*packet_row(packet, resolver))

    return table


def build_stats_panel(
    stats: PacketStats,
    interface: str,
    started_at: datetime,
) -> Panel:
    elapsed = datetime.now() - started_at
    elapsed_seconds = int(elapsed.total_seconds())
    lines = [
        f"Interface      : {interface}",
        "Filter         : ICMP only",
        f"Elapsed        : {elapsed_seconds}s",
        f"Packets total  : {stats.total}",
        f"Sent by me     : {stats.sent}",
        f"Received by me : {stats.received}",
        f"Echo requests  : {stats.echo_requests}",
        f"Echo replies   : {stats.echo_replies}",
        f"Req-reply gap  : {stats.request_reply_gap}",
        f"Other ICMP     : {stats.other_icmp}",
        f"Unparsed lines : {stats.unparsed_lines}",
    ]

    if stats.last_unparsed:
        lines.append(f"Last unparsed  : {stats.last_unparsed[:80]}")
    else:
        lines.append("Last unparsed  : -")

    return Panel("\n".join(lines), title="Capture Stats", border_style="blue")


def build_screen(
    packets: list[IcmpPacket],
    stats: PacketStats,
    resolver: HostResolver,
    interface: str,
    started_at: datetime,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Group:
    # Evidence first: the packet table is the raw observation, the stats
    # panel is only interpretation of it. Never crop the evidence.
    return Group(
        build_packet_table(packets, resolver, max_rows),
        build_stats_panel(stats, interface, started_at),
    )
