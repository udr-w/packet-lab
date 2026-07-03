"""Resolve IP addresses into names we can read quickly."""

import socket
import subprocess


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

