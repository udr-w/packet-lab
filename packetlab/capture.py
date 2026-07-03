"""Packet capture helpers.

This module knows how to ask tcpdump for ICMP packets. It does not parse
packets and it does not decide how they should be displayed.
"""

import subprocess
from collections.abc import Iterator


def start_icmp_capture(interface: str) -> subprocess.Popen[str]:
    """Start tcpdump for ICMP traffic on one interface."""
    cmd = [
        "tcpdump",
        "-i",
        interface,
        "-nn",
        "-tttt",
        "-l",
        "icmp",
    ]

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def iter_lines(process: subprocess.Popen[str]) -> Iterator[str]:
    """Yield stripped stdout lines from a running capture process."""
    if process.stdout is None:
        return

    for line in process.stdout:
        yield line.strip()
