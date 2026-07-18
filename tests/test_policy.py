"""Command and capability policy — accept and reject paths for every category."""

import unittest
from pathlib import Path
import tempfile

from packetlab.lab.policy import (check_capabilities, check_command,
                                  check_path_input, is_within)
from packetlab.lab.specs import ToolSpec


def _spec(read=(), write=()):
    spec, result = ToolSpec.from_dict({
        "id": "t", "purpose": "p", "lesson_id": "v1.1",
        "inputs": {"f": {"type": "path", "access": "read"}},
        "outputs": {"n": {"type": "integer"}},
        "capabilities": {"commands": [], "filesystem": {"read": list(read),
                                                        "write": list(write)},
                         "network": "none"},
        "limits": {"timeout_seconds": 5, "max_output_bytes": 1000},
        "dependencies": {"python": ["standard-library-only"]}, "retention": "lesson"})
    assert spec is not None, result.errors
    return spec


class CommandPolicy(unittest.TestCase):
    ws = Path("/tmp")

    CASES = [
        # argv, category, expected_allowed
        (["ping", "-c", "3", "127.0.0.1"], "ping", True),
        (["ping", "127.0.0.1"], "ping", False),          # unbounded
        (["ping", "-c", "50", "8.8.8.8"], "ping", False),  # over bound
        (["dig", "example.com"], "dns_query", True),
        (["ip", "route", "show"], "observe_network", True),
        (["ss", "-tunp"], "observe_network", True),
        (["tcpdump", "-i", "lo", "-nn", "-tttt", "-l", "icmp"], "capture", True),
        (["tcpdump", "-i", "lo", "-z", "sh", "icmp"], "capture", False),
        (["tcpdump", "-i", "lo", "-r", "/etc/shadow"], "capture", False),
        (["tcpdump", "-i", "lo", "-Z", "root", "icmp"], "capture", False),
        (["tcpdump", "-nnvz", "icmp"], "capture", False),  # bundled unknown
        (["cat", "/etc/resolv.conf"], "read_system_file", True),
        (["cat", "/proc/net/arp"], "read_system_file", True),
        (["cat", "/etc/shadow"], "read_system_file", False),
        (["cat", "/proc/net/../../etc/shadow"], "read_system_file", False),
        (["ip", "neigh", "del", "192.168.8.1", "dev", "wlp0s20f3"],
         "modify_neighbour_cache", True),
        (["ip", "link", "add", "x"], "modify_neighbour_cache", False),
        (["rm", "-rf", "/"], "observe_network", False),   # not allowlisted
        (["ping", "-c", "3", "127.0.0.1"], "bogus_category", False),
    ]

    def test_command_matrix(self):
        for argv, category, expected in self.CASES:
            with self.subTest(argv=argv, category=category):
                decision = check_command(argv, category, self.ws)
                self.assertEqual(decision.allowed, expected,
                                 f"{argv} -> {decision.reason}")

    def test_control_characters_rejected(self):
        self.assertFalse(check_command(["ping", "-c", "3\n rm", "x"], "ping",
                                       self.ws).allowed)

    def test_workspace_write_path_confined(self):
        with tempfile.TemporaryDirectory() as ws:
            ws_path = Path(ws)
            self.assertTrue(check_command(
                ["tcpdump", "-i", "lo", "-w", "out.pcap", "icmp"], "capture",
                ws_path).allowed)
            self.assertFalse(check_command(
                ["tcpdump", "-i", "lo", "-w", "/etc/x.pcap", "icmp"], "capture",
                ws_path).allowed)


class CapabilityPolicy(unittest.TestCase):
    def test_network_must_be_none(self):
        # from_dict already forces network none, so build a spec then tamper.
        spec = _spec()
        object.__setattr__(spec, "capability_network", "outbound")
        self.assertFalse(check_capabilities(spec, [], Path("/tmp")).allowed)

    def test_commands_rejected(self):
        spec = _spec()
        object.__setattr__(spec, "capability_commands", ["tcpdump"])
        self.assertFalse(check_capabilities(spec, [], Path("/tmp")).allowed)

    def test_write_outside_workspace_rejected(self):
        with tempfile.TemporaryDirectory() as ws:
            spec = _spec(write=["/etc/passwd"])
            self.assertFalse(check_capabilities(spec, [], Path(ws)).allowed)

    def test_write_inside_workspace_ok(self):
        with tempfile.TemporaryDirectory() as ws:
            spec = _spec(write=["out/*.txt"])
            self.assertTrue(check_capabilities(spec, [], Path(ws)).allowed)

    def test_read_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as ws:
            spec = _spec(read=["../../etc/*"])
            self.assertFalse(check_capabilities(spec, [], Path(ws)).allowed)


class PathInput(unittest.TestCase):
    def test_declared_read_path_accepted(self):
        with tempfile.TemporaryDirectory() as ws:
            spec = _spec(read=["*.txt"])
            self.assertTrue(check_path_input("capture.txt", spec, Path(ws)).allowed)

    def test_undeclared_path_rejected(self):
        with tempfile.TemporaryDirectory() as ws:
            spec = _spec(read=["*.txt"])
            self.assertFalse(check_path_input("/etc/passwd", spec, Path(ws)).allowed)


class IsWithin(unittest.TestCase):
    def test_symlink_leaf_rejected(self):
        with tempfile.TemporaryDirectory() as base:
            base_path = Path(base)
            target = base_path / "evil"
            target.symlink_to("/etc/passwd")
            self.assertFalse(is_within(base_path, target))

    def test_plain_child_ok(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertTrue(is_within(Path(base), Path(base) / "sub" / "file"))


if __name__ == "__main__":
    unittest.main()
