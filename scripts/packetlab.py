#!/usr/bin/env python3

from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_INTERFACE = "wlp0s20f3"


def interface_from_args(argv: list[str]) -> str:
    if len(argv) > 1:
        return argv[1]

    return DEFAULT_INTERFACE


def main():
    interface = interface_from_args(sys.argv)

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

    from packetlab.capture import iter_lines, start_icmp_capture
    from packetlab.parser import IcmpPacket, parse_tcpdump_line
    from packetlab.resolver import HostResolver
    from packetlab.stats import PacketStats
    from packetlab.ui import build_screen

    console = Console()

    resolver = HostResolver()
    stats = PacketStats()
    packets: list[IcmpPacket] = []
    started_at = datetime.now()

    console.print(f"Listening on interface: [bold]{interface}[/bold]")
    console.print("Filter: ICMP only")
    console.print("Press Ctrl+C to stop.")

    process = start_icmp_capture(interface)
    stopped_by_user = False

    try:
        with Live(
            build_screen(packets, stats, resolver, interface, started_at),
            console=console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            for line in iter_lines(process):
                packet = parse_tcpdump_line(line)

                if packet is None:
                    stats.observe_unparsed(line)
                    live.update(
                        build_screen(packets, stats, resolver, interface, started_at)
                    )
                    continue

                packets.append(packet)
                stats.observe(packet, resolver.my_ips)

                live.update(
                    build_screen(packets, stats, resolver, interface, started_at)
                )

    except KeyboardInterrupt:
        console.print("\nStopped.")
        process.terminate()
        process.wait(timeout=2)
        stopped_by_user = True

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
