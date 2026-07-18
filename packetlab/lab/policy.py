"""Deterministic command and capability policy.

Every command the agent wants to run on the learner's machine is checked
here first: known category, allowlisted binary, no denied flags, path
arguments inside allowed roots. There is no shell anywhere — argv lists
only — so quoting tricks and interpolation never reach an interpreter.

The policy is data (tables below), the enforcement is code, and the tests
exercise both accept and reject paths for every category.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
from pathlib import Path

from packetlab.lab.specs import ToolSpec


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    rule: str

    @staticmethod
    def deny(reason: str, rule: str) -> "Decision":
        return Decision(allowed=False, reason=reason, rule=rule)

    @staticmethod
    def allow(reason: str, rule: str) -> "Decision":
        return Decision(allowed=True, reason=reason, rule=rule)


@dataclass(frozen=True)
class BinaryRule:
    """Constraints for one allowlisted binary within a category.

    Two enforcement styles are supported. Most binaries use a deny-list of
    dangerous flags. The highest-risk binary (tcpdump, which has -z postrotate
    command execution) uses ``allowed_flags`` instead: an allow-by-exception
    list where any token not explicitly permitted is rejected. Allow-listing
    is the stronger stance — see ADR-0002 — and is preferred for anything that
    can touch files or spawn processes.
    """

    # Deny-list mode: flags that are rejected outright.
    denied_flags: tuple = ()
    # Allow-list mode: if non-empty, ONLY these flags are permitted and every
    # other dashed token is denied. Value-taking flags are declared separately.
    allowed_flags: tuple = ()
    # Flags whose *next* argument is a filesystem path that must stay
    # inside the lesson workspace (e.g. tcpdump -w).
    workspace_path_flags: tuple = ()
    # If set, every non-flag positional that looks like a path must match
    # one of these glob patterns (used for cat/head on system files).
    path_allowlist: tuple = ()
    # If set, this flag is mandatory (e.g. ping must be count-bounded).
    required_flags: tuple = ()
    # Upper bound for the integer argument of a flag, e.g. ("-c", 20).
    bounded_int_flags: dict = field(default_factory=dict)


# Read-only paths a lesson may inspect with read_system_file commands.
# /run/systemd/resolve entries are here because /etc/resolv.conf is a symlink
# into that directory on Ubuntu; both the link and its target must be listed
# since policy checks the path as given AND fully resolved.
READABLE_SYSTEM_PATHS = (
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/run/systemd/resolve/stub-resolv.conf",
    "/run/systemd/resolve/resolv.conf",
    "/proc/net/*",
    "/proc/self/net/*",
    "/proc/[0-9]*/net/*",
    "/proc/sys/net/*",
    "/sys/class/net/*",
    "/sys/class/net/*/*",
)

COMMAND_CATEGORIES: dict[str, dict[str, BinaryRule]] = {
    # Read-only queries of live network state.
    "observe_network": {
        "ip": BinaryRule(denied_flags=("-b", "-batch", "-force")),
        "ss": BinaryRule(),
        "resolvectl": BinaryRule(),
        "getent": BinaryRule(),
        "hostname": BinaryRule(),
        "getcap": BinaryRule(),
    },
    # DNS lookups (these do emit packets — that is the point of the lesson).
    "dns_query": {
        "dig": BinaryRule(),
        "host": BinaryRule(),
    },
    # ICMP echo, always count-bounded so it terminates on its own.
    "ping": {
        "ping": BinaryRule(required_flags=("-c",), bounded_int_flags={"-c": 20}),
    },
    # Packet capture — the highest-risk binary, so allow-by-exception. Only
    # the flags a lesson genuinely needs are permitted; -z (postrotate command
    # execution), -F (filter file), -r (read arbitrary savefile), -Z/-V and
    # every unrecognised token are denied by falling through the allowlist.
    # -w takes a path that must resolve inside the lesson workspace; -c/-C/-G
    # take bounded integers. Filter expressions arrive as trailing positionals.
    "capture": {
        "tcpdump": BinaryRule(
            allowed_flags=("-i", "-n", "-nn", "-e", "-t", "-tt", "-ttt",
                           "-tttt", "-l", "-q", "-x", "-xx", "-X", "-XX", "-A",
                           "-c", "-C", "-G", "-s", "-w"),
            workspace_path_flags=("-w",),
            bounded_int_flags={"-c": 10_000, "-C": 100, "-G": 3600, "-s": 65535},
        ),
    },
    # Reading specific system files the lessons study.
    "read_system_file": {
        "cat": BinaryRule(path_allowlist=READABLE_SYSTEM_PATHS),
        "head": BinaryRule(path_allowlist=READABLE_SYSTEM_PATHS),
    },
    # Mutations used by lessons (e.g. `ip neigh del` in the ARP lesson).
    # Deliberately narrow: only `ip neigh del/flush` shapes are allowed.
    "modify_neighbour_cache": {
        "ip": BinaryRule(),
    },
}

# Extra structural constraint for the one mutating category we allow.
_NEIGH_VERBS = ("del", "delete", "flush")


def known_categories() -> list[str]:
    return sorted(COMMAND_CATEGORIES)


def is_within(base: Path, candidate: Path) -> bool:
    """True when candidate resolves to a location inside base.

    The parent directory is resolved (following any symlinks), then the final
    component is appended without following it, and it is rejected if that
    final component is itself a symlink. This blocks the common escape where
    an approved output path's leaf is a symlink pointing outside the workspace.
    A residual TOCTOU window remains for files a child process opens itself
    (e.g. tcpdump -w) — documented in docs/threat-model.md, not hidden.
    """
    try:
        resolved_base = base.resolve(strict=False)
        parent = candidate.parent.resolve(strict=False)
        final = parent / candidate.name
        if candidate.name not in ("", ".", "..") and final.is_symlink():
            return False
    except (OSError, RuntimeError):
        return False
    return final == resolved_base or resolved_base in final.parents or final == resolved_base


def _split_eq_flags(args: list[str]) -> list[str]:
    """Turn ['-s=100', '--flag=v'] into ['-s', '100', '--flag', 'v'].

    Leaves filter expressions and non-flag tokens untouched. Bundled short
    flags (e.g. '-nnvz') are deliberately NOT expanded: under an allow-list an
    unrecognised bundle is simply denied, which is the safe outcome.
    """
    out: list[str] = []
    for arg in args:
        if arg.startswith("-") and "=" in arg and not arg.startswith("--="):
            flag, _, value = arg.partition("=")
            out.append(flag)
            out.append(value)
        else:
            out.append(arg)
    return out


def _looks_like_path(token: str) -> bool:
    return token.startswith(("/", "./", "../", "~")) or token in (".", "..")


def _matches_allowlist(token: str, allowlist: tuple) -> bool:
    """Both the path as given (normalised) and its symlink-resolved target
    must be allowlisted — the former stops confused-deputy prefixes, the
    latter stops symlinks pointing at sensitive files."""
    import os.path
    as_given = os.path.normpath(os.path.join("/", token) if not token.startswith("/")
                                else token)
    resolved = str(Path(token).resolve(strict=False))
    def hit(path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in allowlist)
    return hit(as_given) and hit(resolved)


def check_command(argv: list[str], category: str, workspace: Path) -> Decision:
    """May this argv run under this category? Deny-by-default at every level."""
    if not argv or not all(isinstance(a, str) and a for a in argv):
        return Decision.deny("argv must be a non-empty list of non-empty strings",
                             "argv-shape")
    for arg in argv:
        if "\x00" in arg or "\n" in arg or "\r" in arg:
            return Decision.deny("argv contains control characters", "argv-control-chars")

    if category not in COMMAND_CATEGORIES:
        return Decision.deny(f"unknown command category '{category}'", "category-unknown")

    binary = Path(argv[0]).name
    if binary != argv[0] and not argv[0].startswith(("/usr/bin/", "/usr/sbin/", "/bin/")):
        return Decision.deny("binary must be a bare name or under /usr/bin, /usr/sbin, /bin",
                             "binary-path")
    rules = COMMAND_CATEGORIES[category]
    if binary not in rules:
        return Decision.deny(
            f"'{binary}' is not allowlisted for category '{category}'", "binary-allowlist")
    rule = rules[binary]

    # Split any "--flag=value" / "-s=100" forms so the walk sees flag and
    # value separately and an allow-list cannot be bypassed by joining them.
    args = _split_eq_flags(argv[1:])
    for flag in rule.required_flags:
        if flag not in args:
            return Decision.deny(f"'{binary}' requires flag {flag} in this category",
                                 "required-flag")

    value_flags = (set(rule.workspace_path_flags) | set(rule.bounded_int_flags)
                   | {"-i", "-s"})
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in rule.denied_flags:
            return Decision.deny(f"flag {arg} is denied for '{binary}'", "denied-flag")
        if rule.allowed_flags and arg.startswith("-") and arg != "--":
            if arg not in rule.allowed_flags:
                return Decision.deny(
                    f"flag {arg} is not on the allow-list for '{binary}'",
                    "flag-not-allowlisted")
        if arg in rule.workspace_path_flags:
            if i + 1 >= len(args):
                return Decision.deny(f"{arg} needs a path argument", "flag-missing-path")
            target = Path(args[i + 1])
            if target.name != args[i + 1] and not is_within(workspace, target):
                return Decision.deny(
                    f"{arg} path must stay inside the lesson workspace", "workspace-path")
            if target.name == args[i + 1] and "/" in args[i + 1]:
                return Decision.deny(f"{arg} path is malformed", "workspace-path")
            i += 2
            continue
        if arg in rule.bounded_int_flags:
            if i + 1 >= len(args):
                return Decision.deny(f"{arg} needs an integer argument", "flag-missing-int")
            try:
                value = int(args[i + 1])
            except ValueError:
                return Decision.deny(f"{arg} argument must be an integer", "flag-int")
            if not (1 <= value <= rule.bounded_int_flags[arg]):
                return Decision.deny(
                    f"{arg} {value} exceeds bound {rule.bounded_int_flags[arg]}",
                    "flag-bound")
            i += 2
            continue
        if rule.path_allowlist and _looks_like_path(arg):
            if not _matches_allowlist(arg, rule.path_allowlist):
                return Decision.deny(
                    f"path '{arg}' is outside the readable-system-file allowlist",
                    "path-allowlist")
        elif _looks_like_path(arg) and not rule.path_allowlist:
            # Binaries without a path allowlist get no positional path args at
            # all (their legitimate lesson usage never needs one).
            if arg not in (".",):
                return Decision.deny(
                    f"'{binary}' may not take filesystem path arguments here",
                    "path-unexpected")
        i += 1

    if category == "modify_neighbour_cache":
        if len(argv) < 3 or argv[1] not in ("neigh", "neighbour", "neighbor") \
                or argv[2] not in _NEIGH_VERBS:
            return Decision.deny(
                "only 'ip neigh del|flush ...' is permitted in modify_neighbour_cache",
                "neigh-shape")

    return Decision.allow(f"'{binary}' permitted under '{category}'", "allow")


def check_capabilities(spec: ToolSpec, permitted_categories: list[str],
                       workspace: Path) -> Decision:
    """Are a tool spec's requested capabilities acceptable for this lesson?

    Generated tools are parsers/summarisers: no network, no commands unless
    the lesson explicitly grants a category, writes only inside the workspace.
    """
    if spec.capability_network != "none":
        return Decision.deny("generated tools may not request network access",
                             "cap-network")
    if spec.capability_commands:
        return Decision.deny(
            "generated tools may not run external commands; guarded commands "
            "must go through the lesson runner instead", "cap-commands")

    for pattern in spec.capability_fs_write:
        if not _glob_within(workspace, pattern, workspace):
            return Decision.deny(
                f"write capability '{pattern}' escapes the lesson workspace",
                "cap-fs-write")
    for pattern in spec.capability_fs_read:
        if not (_glob_within(workspace, pattern, workspace)
                or _pattern_in_system_allowlist(pattern)):
            return Decision.deny(
                f"read capability '{pattern}' is outside the workspace and the "
                "readable-system-file allowlist", "cap-fs-read")

    del permitted_categories  # reserved for future command-capable tools
    return Decision.allow("capabilities are minimal and inside policy", "allow")


def _glob_within(base: Path, pattern: str, workspace: Path) -> bool:
    """Is a glob pattern rooted inside base once resolved (no .. escapes)?"""
    if "\x00" in pattern or ".." in Path(pattern).parts:
        return False
    candidate = Path(pattern)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    static_prefix = Path(*_static_parts(candidate))
    return is_within(base, static_prefix)


def _static_parts(path: Path) -> list[str]:
    parts = []
    for part in path.parts:
        if any(ch in part for ch in "*?["):
            break
        parts.append(part)
    return parts or ["/nonexistent"]


def _pattern_in_system_allowlist(pattern: str) -> bool:
    if ".." in Path(pattern).parts:
        return False
    return any(
        fnmatch.fnmatch(pattern, allowed) or pattern == allowed
        for allowed in READABLE_SYSTEM_PATHS
    )


def check_path_input(value: str, spec: ToolSpec, workspace: Path) -> Decision:
    """Validate a runtime path input against the tool's declared read globs."""
    if "\x00" in value:
        return Decision.deny("path contains NUL", "path-control-chars")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = str(candidate.resolve(strict=False))
    for pattern in spec.capability_fs_read:
        pattern_path = pattern if Path(pattern).is_absolute() \
            else str((workspace / pattern).resolve(strict=False))
        if fnmatch.fnmatch(resolved, pattern_path):
            return Decision.allow("path matches a declared read capability", "allow")
    return Decision.deny(
        f"path '{value}' does not match any declared read capability", "path-capability")
