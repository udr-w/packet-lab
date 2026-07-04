"""Rich terminal rendering for the packet viewer."""

from datetime import datetime

from rich.console import Group
from rich.panel import Panel
from rich.table import Table

from packetlab.capture import capture_command
from packetlab.parser import ArpPacket, IcmpPacket
from packetlab.resolver import HostResolver, MacResolver
from packetlab.stats import ArpStats, PacketStats


DEFAULT_MAX_ROWS = 20

# Terminal lines consumed by everything that is not a packet row:
# the stats panel (12-13 text lines + 2 border lines) and the table's
# own title, header, and border lines.
STATS_PANEL_LINES = 15
TABLE_CHROME_LINES = 5


def row_budget(terminal_height: int, lines_per_row: int = 1) -> int:
    """How many packet rows fit on screen alongside the stats panel.

    ARP rows carry a label line under each MAC, so they are two terminal
    lines tall — pass lines_per_row=2 there to keep the table on screen.
    """
    available = terminal_height - STATS_PANEL_LINES - TABLE_CHROME_LINES
    return max(3, available // lines_per_row)


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
        f"Running        : {' '.join(capture_command(interface, 'icmp'))}",
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


def labeled_mac(mac: str, resolver: MacResolver) -> str:
    """The raw MAC plus, whenever we know one, its human meaning beside it."""
    label = resolver.label_mac(mac)

    if label is None:
        return mac

    if label.startswith("broadcast"):
        return f"{mac}\n[bold red]({label})[/bold red]"

    return f"{mac}\n[bold bright_white]({label})[/bold bright_white]"


def arp_packet_row(packet: ArpPacket, resolver: MacResolver) -> tuple[str, ...]:
    return (
        packet.short_time,
        labeled_mac(packet.source_mac, resolver),
        labeled_mac(packet.destination_mac, resolver),
        packet.operation,
        resolver.annotate(packet.detail),
    )


def build_arp_table(
    packets: list[ArpPacket],
    resolver: MacResolver,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Table:
    table = Table(title="ARP Packets", expand=True)
    table.add_column("Time", style="cyan", no_wrap=True)
    table.add_column("Source MAC", style="green", no_wrap=True)
    table.add_column("Destination MAC", style="green")
    table.add_column("Op", style="magenta", no_wrap=True)
    table.add_column("Message", style="yellow")

    for packet in packets[-max_rows:]:
        table.add_row(*arp_packet_row(packet, resolver))

    return table


def build_arp_stats_panel(
    stats: ArpStats,
    interface: str,
    started_at: datetime,
) -> Panel:
    elapsed = datetime.now() - started_at
    elapsed_seconds = int(elapsed.total_seconds())
    command = capture_command(interface, "arp", show_link_level=True)
    lines = [
        f"Interface        : {interface}",
        "Filter           : ARP only",
        f"Running          : {' '.join(command)}",
        f"Elapsed          : {elapsed_seconds}s",
        f"Packets total    : {stats.total}",
        f"Requests         : {stats.requests}",
        f"Replies          : {stats.replies}",
        f"Broadcast frames : {stats.broadcast_frames}",
        f"Unicast frames   : {stats.unicast_frames}",
        f"Unparsed lines   : {stats.unparsed_lines}",
    ]

    if stats.last_unparsed:
        lines.append(f"Last unparsed    : {stats.last_unparsed[:80]}")
    else:
        lines.append("Last unparsed    : -")

    return Panel("\n".join(lines), title="Capture Stats", border_style="blue")


def build_arp_screen(
    packets: list[ArpPacket],
    stats: ArpStats,
    resolver: MacResolver,
    interface: str,
    started_at: datetime,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Group:
    return Group(
        build_arp_table(packets, resolver, max_rows),
        build_arp_stats_panel(stats, interface, started_at),
    )
