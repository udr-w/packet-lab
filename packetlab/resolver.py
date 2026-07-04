"""Resolve IPs and MACs into names a human can read at a glance.

Project rule: raw values stay on screen (they are the evidence), but any
value a human cannot read at a glance gets a plain-language label beside it.
"""

import re
import socket
import subprocess
import time

from packetlab.parser import BROADCAST_MAC


class HostResolver:
    """Resolve local IPs as Me and cache reverse DNS lookups."""

    def __init__(self) -> None:
        self.my_ips = self._get_my_ips()
        self._cache: dict[str, str] = {}

    def resolve(self, ip: str) -> str:
        if ip in self.my_ips:
            return "Me"

        if ip in self._cache:
            return self._cache[ip]

        try:
            value = socket.gethostbyaddr(ip)[0]
        except Exception:
            value = ip

        self._cache[ip] = value
        return value

    def is_me(self, ip: str) -> bool:
        return ip in self.my_ips

    @staticmethod
    def _get_my_ips() -> set[str]:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=False,
        )

        ips = set(result.stdout.strip().split())
        ips.add("127.0.0.1")
        return ips


IP_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
MAC_PATTERN = re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b")


class MacResolver:
    """Label MAC addresses (and LAN IPs) with what they mean on THIS machine.

    Labels come from the machine itself, the same places the lessons look:
    the interface's own address file, the default route's gateway, and the
    kernel's neighbour table (`ip neigh`). The neighbour table is re-read
    when an unknown MAC appears (throttled), because ARP itself changes it.
    """

    REFRESH_SECONDS = 5.0

    def __init__(self, interface: str) -> None:
        self.interface = interface
        self._names = HostResolver()
        self.my_ips = self._names.my_ips
        self.my_mac = self._read_my_mac(interface)
        self.gateway_ip = self._read_gateway_ip()
        self._mac_to_ip: dict[str, str] = {}
        self._last_refresh = 0.0
        self._refresh_neighbours()

    def label_mac(self, mac: str) -> str | None:
        """A short human meaning for a MAC, or None when we have none."""
        if mac == BROADCAST_MAC:
            return "broadcast: everyone on this LAN"

        if mac == self.my_mac:
            return "me"

        ip = self._mac_to_ip.get(mac)

        if ip is None:
            self._maybe_refresh_neighbours()
            ip = self._mac_to_ip.get(mac)

        if ip is None:
            return None

        if ip == self.gateway_ip:
            return "router"

        if ip in self.my_ips:
            return "me"

        # Reverse DNS: home routers usually serve the names their DHCP
        # leases registered (e.g. Udara-s-S24-Ultra). Falls back to the IP.
        return self._names.resolve(ip)

    def label_ip(self, ip: str) -> str | None:
        if ip in self.my_ips:
            return "me"

        if ip == self.gateway_ip:
            return "router"

        name = self._names.resolve(ip)
        return name if name != ip else None

    def annotate(self, text: str) -> str:
        """Add labels beside every IP and MAC found in free text.

        'who-has 192.168.8.1 tell 192.168.8.173' becomes
        'who-has 192.168.8.1 (router) tell 192.168.8.173 (me)'.
        """

        def ip_label(match: re.Match[str]) -> str:
            label = self.label_ip(match.group(0))
            return f"{match.group(0)} ({label})" if label else match.group(0)

        def mac_label(match: re.Match[str]) -> str:
            label = self.label_mac(match.group(0))

            if label is None or label == match.group(0):
                return match.group(0)

            return f"{match.group(0)} ({label})"

        return MAC_PATTERN.sub(mac_label, IP_PATTERN.sub(ip_label, text))

    def _maybe_refresh_neighbours(self) -> None:
        if time.monotonic() - self._last_refresh >= self.REFRESH_SECONDS:
            self._refresh_neighbours()

    def _refresh_neighbours(self) -> None:
        self._last_refresh = time.monotonic()
        result = subprocess.run(
            ["ip", "neigh", "show"],
            capture_output=True,
            text=True,
            check=False,
        )

        for line in result.stdout.splitlines():
            parts = line.split()

            if "lladdr" in parts:
                ip = parts[0]
                mac = parts[parts.index("lladdr") + 1]
                self._mac_to_ip[mac] = ip

    @staticmethod
    def _read_my_mac(interface: str) -> str:
        try:
            with open(f"/sys/class/net/{interface}/address") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    @staticmethod
    def _read_gateway_ip() -> str:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            check=False,
        )

        parts = result.stdout.split()

        if "via" in parts:
            return parts[parts.index("via") + 1]

        return ""

