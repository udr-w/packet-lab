#!/usr/bin/env python3

from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_INTERFACE = "wlp0s20f3"
MODES = ("icmp", "arp")


def mode_and_interface_from_args(argv: list[str]) -> tuple[str, str]:
    """Args in any order: a known mode name selects the mode ('icmp' default),
    anything else is the interface."""
    mode = "icmp"
    interface = DEFAULT_INTERFACE

    for arg in argv[1:]:
        if arg in MODES:
            mode = arg
        else:
            interface = arg

    return mode, interface


def main():
    mode, interface = mode_and_interface_from_args(sys.argv)

    try:
        from rich.console import Console
        from rich.live import Live
    except ModuleNotFoundError:
        print("Packet Lab needs the Rich Python package for the terminal UI.")
        print()
        print("Install it, then run the viewer again:")
        print()
        print("  sudo apt install python3-rich")
        print(f"  python3 {Path(__file__)} {interface}")
        return

    from packetlab.capture import iter_lines, start_arp_capture, start_icmp_capture
    from packetlab.parser import parse_arp_line, parse_tcpdump_line
    from packetlab.resolver import HostResolver, MacResolver
    from packetlab.stats import ArpStats, PacketStats
    from packetlab.ui import build_arp_screen, build_screen, row_budget

    console = Console()

    packets = []
    started_at = datetime.now()

    if mode == "arp":
        stats = ArpStats()
        mac_resolver = MacResolver(interface)
        parse_line = parse_arp_line
        start_capture = start_arp_capture
        observe_packet = stats.observe

        def current_screen():
            return build_arp_screen(
                packets,
                stats,
                mac_resolver,
                interface,
                started_at,
                row_budget(console.size.height, lines_per_row=2),
            )

    else:
        resolver = HostResolver()
        stats = PacketStats()
        parse_line = parse_tcpdump_line
        start_capture = start_icmp_capture

        def observe_packet(packet):
            stats.observe(packet, resolver.my_ips)

        def current_screen():
            return build_screen(
                packets,
                stats,
                resolver,
                interface,
                started_at,
                row_budget(console.size.height),
            )

    console.print(f"Listening on interface: [bold]{interface}[/bold]")
    console.print(f"Filter: {mode.upper()} only")
    console.print("Press Ctrl+C to stop.")

    process = start_capture(interface)
    stopped_by_user = False

    try:
        with Live(
            current_screen(),
            console=console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            for line in iter_lines(process):
                packet = parse_line(line)

                if packet is None:
                    stats.observe_unparsed(line)
                else:
                    packets.append(packet)
                    observe_packet(packet)

                live.update(current_screen())

    except KeyboardInterrupt:
        process.terminate()
        process.wait(timeout=2)
        stopped_by_user = True
        # The alternate screen vanished with everything on it; reprint the
        # final state to the normal buffer so the evidence can be studied.
        console.print("Stopped. Final capture state:")
        console.print(current_screen())

    if not stopped_by_user:
        exit_code = process.wait()
        stderr_output = process.stderr.read() if process.stderr else ""

        console.print(
            f"[bold]tcpdump for interface '{interface}' ended[/bold] "
            f"(exit code {exit_code})."
        )

        if stderr_output.strip():
            console.print("[bold red]tcpdump said:[/bold red]")
            console.print(stderr_output.strip())
        elif exit_code != 0:
            console.print(
                "[yellow]No stderr output was captured, but tcpdump exited "
                "with a non-zero code.[/yellow]"
            )


if __name__ == "__main__":
    main()
