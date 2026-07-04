"""Packet capture helpers.

This module knows how to ask tcpdump for packets. It does not parse
packets and it does not decide how they should be displayed.
"""

import subprocess
from collections.abc import Iterator


def capture_command(
    interface: str,
    tcpdump_filter: str,
    show_link_level: bool = False,
) -> list[str]:
    """The exact tcpdump invocation for a capture.

    Exposed separately so the UI can show the student precisely what their
    instrument is running — the tool must never be a black box.

    show_link_level adds -e so frame (MAC) headers appear — needed for ARP,
    where the link-layer addresses are the whole point.
    """
    cmd = ["tcpdump", "-i", interface, "-nn", "-tttt", "-l"]

    if show_link_level:
        cmd.append("-e")

    cmd.append(tcpdump_filter)
    return cmd


def start_capture(
    interface: str,
    tcpdump_filter: str,
    show_link_level: bool = False,
) -> subprocess.Popen[str]:
    """Start tcpdump on one interface with the given capture filter."""
    cmd = capture_command(interface, tcpdump_filter, show_link_level)

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def start_icmp_capture(interface: str) -> subprocess.Popen[str]:
    """Start tcpdump for ICMP traffic on one interface."""
    return start_capture(interface, "icmp")


def start_arp_capture(interface: str) -> subprocess.Popen[str]:
    """Start tcpdump for ARP traffic, with MAC headers visible."""
    return start_capture(interface, "arp", show_link_level=True)


def iter_lines(process: subprocess.Popen[str]) -> Iterator[str]:
    """Yield stripped stdout lines from a running capture process."""
    if process.stdout is None:
        return

    for line in process.stdout:
        stripped = line.strip()

        # tcpdump never prints meaningful blank lines; an empty line only
        # appears while the process is shutting down. Yielding it would make
        # the viewer count a phantom "unparsed" packet.
        if stripped:
            yield stripped
