"""Restricted subprocess execution.

This is a *restricted runner*, deliberately not called a sandbox: it is
resource limits + a scrubbed environment + process-group termination, NOT an
isolation boundary. It has no namespaces, no seccomp, and no network cut-off.
Its job is to bound blast radius (time, memory, processes, file size, output)
and to guarantee no lingering children — while the AST validator (toolgen.py)
does the heavier lifting of keeping dangerous code from running at all.
Neither layer is a proof; see docs/threat-model.md for the honest limits.

Enforcement primaries:
- wall-clock deadline in the PARENT (the authority; kills the process group
  the instant it passes, regardless of CPU use, sleeps, or drip output);
- RLIMIT_CPU / RLIMIT_AS / RLIMIT_NPROC / RLIMIT_FSIZE as backstops;
- a fully replaced, minimal environment (never a copy of os.environ);
- refusal to run as root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import selectors
import signal
import subprocess
import time

try:
    import resource
except ImportError:  # pragma: no cover - non-Unix
    resource = None

# Backstop limits (the wall-clock deadline below is the primary time control).
CPU_GRACE_SECONDS = 5
ADDRESS_SPACE_BYTES = 1536 * 1024 * 1024  # 1.5 GiB — CPython runs comfortably
# Extra processes an untrusted tool may create over current usage. Single-module
# stdlib tools need +1 (unittest +1); the headroom blocks a fork bomb. NOT
# applied to trusted allowlisted binaries (dig/tcpdump spawn threads and would
# trip a low per-user cap) — see run_restricted(process_headroom=...).
PROCESS_HEADROOM = 24
MAX_FILE_BYTES = 8 * 1024 * 1024
READ_CHUNK = 65536

# The only environment a restricted child sees. No secrets, no inherited PATH.
BASE_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LC_ALL": "C",
    "LANG": "C",
    "PYTHONBREAKPOINT": "0",  # neutralise breakpoint() even if it slips the AST
    "PYTHONDONTWRITEBYTECODE": "1",
}


@dataclass
class ExecutionResult:
    status: str  # ok | nonzero | timeout | output_cap | error | refused
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    detail: str = ""

    def to_summary(self) -> dict:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "detail": self.detail,
        }


def _count_user_processes() -> int:
    """Best-effort count of processes owned by the current euid (via /proc)."""
    euid = os.geteuid()
    count = 0
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                if os.stat(f"/proc/{entry}").st_uid == euid:
                    count += 1
            except OSError:
                continue
    except OSError:
        return 512  # fall back to a generous cap if /proc is unreadable
    return count


def _preexec(timeout_s: int, nproc_cap: int | None):  # pragma: no cover - child
    """Runs in the child after fork, before exec: new session + rlimits."""
    os.setsid()
    if resource is None:
        return
    cpu = timeout_s + CPU_GRACE_SECONDS
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))
    if nproc_cap is not None:
        resource.setrlimit(resource.RLIMIT_NPROC, (nproc_cap, nproc_cap))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))
    except (ValueError, OSError):
        pass  # some hosts refuse; wall-clock still bounds the child


def _clean_env(env_extra: dict | None) -> dict:
    env = dict(BASE_ENV)
    if env_extra:
        for key, value in env_extra.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("env_extra keys and values must be strings")
            if not key.isidentifier() or "\x00" in value or "\n" in value:
                raise ValueError(f"env_extra key/value rejected: {key!r}")
            env[key] = value
    return env


def run_restricted(argv: list[str], *, cwd, timeout_s: int, max_output_bytes: int,
                   env_extra: dict | None = None, stdin_data: str | None = None,
                   allow_root: bool = False, limit_processes: bool = False
                   ) -> ExecutionResult:
    """Run argv (never a shell) under resource limits and a wall-clock deadline.

    ``limit_processes`` applies a per-user process cap (headroom over current
    usage) — set it True for untrusted generated tools, False for trusted
    allowlisted binaries (dig/tcpdump spawn threads and would trip the cap).
    """
    if not argv or not all(isinstance(a, str) and a for a in argv):
        return ExecutionResult("error", None, "", "", 0, detail="empty/invalid argv")
    if os.geteuid() == 0 and not allow_root:
        return ExecutionResult("refused", None, "", "",
                               0, detail="refusing to run as root")
    nproc_cap = (_count_user_processes() + PROCESS_HEADROOM) if limit_processes else None

    try:
        env = _clean_env(env_extra)
    except ValueError as exc:
        return ExecutionResult("error", None, "", "", 0, detail=str(exc))
    # HOME points at the workspace, never the real home, so a tool that reads
    # ~/.config cannot reach the operator's dotfiles or credentials.
    env["HOME"] = str(cwd)

    start = time.monotonic()
    deadline = start + timeout_s
    try:
        process = subprocess.Popen(
            argv, cwd=str(cwd), env=env,
            stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            preexec_fn=lambda: _preexec(timeout_s, nproc_cap), text=False,
        )
    except (OSError, ValueError) as exc:
        return ExecutionResult("error", None, "", "", 0, detail=f"spawn failed: {exc}")

    if stdin_data is not None and process.stdin:
        try:
            process.stdin.write(stdin_data.encode("utf-8"))
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    try:
        stdout, stderr, status = _pump(process, deadline, max_output_bytes)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
    exit_code = process.poll()
    duration_ms = int((time.monotonic() - start) * 1000)

    out_text, out_trunc = _decode(stdout, max_output_bytes)
    err_text, err_trunc = _decode(stderr, max_output_bytes)

    if status is None:
        if exit_code == 0:
            status = "ok"
        else:
            status = "nonzero"
    return ExecutionResult(status, exit_code, out_text, err_text, duration_ms,
                           stdout_truncated=out_trunc, stderr_truncated=err_trunc,
                           detail=_status_detail(status, exit_code))


def _pump(process, deadline, max_output_bytes):
    """Read stdout/stderr until EOF, cap, or the wall-clock deadline."""
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "out")
    selector.register(process.stderr, selectors.EVENT_READ, "err")
    buffers = {"out": bytearray(), "err": bytearray()}
    status = None
    open_streams = 2

    while open_streams > 0:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            status = "timeout"
            break
        for key, _ in selector.select(timeout=min(remaining, 0.5)):
            chunk = os.read(key.fileobj.fileno(), READ_CHUNK)
            if not chunk:
                selector.unregister(key.fileobj)
                open_streams -= 1
                continue
            buffers[key.data].extend(chunk)
            if (len(buffers["out"]) + len(buffers["err"])) > max_output_bytes * 2:
                status = "output_cap"
                break
        if status:
            break

    selector.close()
    if status in ("timeout", "output_cap") or process.poll() is None:
        _terminate(process)
    else:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _terminate(process)
    return bytes(buffers["out"]), bytes(buffers["err"]), status


def _terminate(process):
    """Kill the whole process group so no child outlives the runner."""
    try:
        pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:  # pragma: no cover
        pass


def _decode(data: bytes, max_output_bytes: int) -> tuple[str, bool]:
    truncated = len(data) > max_output_bytes
    if truncated:
        data = data[:max_output_bytes]
    return data.decode("utf-8", errors="replace"), truncated


def _status_detail(status: str, exit_code) -> str:
    return {
        "ok": "completed successfully",
        "nonzero": f"exited with code {exit_code}",
        "timeout": "killed at wall-clock deadline",
        "output_cap": "killed after exceeding output cap",
    }.get(status, "")
