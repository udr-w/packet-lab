"""Serialised, atomic JSON state files.

State (lesson.json, learner.json, the tool registry) is read-modify-written by
short-lived CLI processes. Claude Code batches Bash calls, so two `lab`
commands can genuinely overlap; a plain load-mutate-save would let the second
writer silently drop the first's update. Every mutation therefore runs under a
single advisory file lock, and each file carries a monotonically increasing
`generation` so a stale write is detected rather than silently applied.

Atomic rename gives crash-safety (a reader never sees a torn file); the lock
gives concurrency-safety (no lost updates). Both are needed.
"""

from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
from typing import Callable

MAX_JSON_BYTES = 5_000_000


class StaleStateError(RuntimeError):
    """Raised when a save is attempted against a generation that has moved on."""


def _lock_path(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / ".lock"


@contextmanager
def state_lock(state_dir: Path):
    """Hold an exclusive advisory lock for the duration of a mutation."""
    lock_file = _lock_path(state_dir)
    handle = open(lock_file, "w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def load_json(path: Path, default: dict | None = None) -> dict:
    """Read a JSON object, rejecting NaN/Infinity and oversize input."""
    if not path.exists():
        return dict(default) if default is not None else {}
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"{path} exceeds {MAX_JSON_BYTES} bytes")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return json.loads(text, parse_constant=_reject_constant)


def _reject_constant(value: str):
    raise ValueError(f"JSON contained forbidden constant {value!r}")


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON via a temp file + rename so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def update_json(path: Path, mutate: Callable[[dict], dict],
                default: dict | None = None) -> dict:
    """Lock, load, mutate, bump generation, and atomically save. Returns new state.

    ``mutate`` receives the current state (a dict) and returns the new state.
    The load and save happen inside one lock hold, so overlapping CLI processes
    serialise instead of clobbering each other.
    """
    state_dir = path.parent
    with state_lock(state_dir):
        current = load_json(path, default=default)
        loaded_generation = current.get("generation", 0)
        new_state = mutate(dict(current))
        if new_state.get("generation", 0) != loaded_generation:
            raise StaleStateError(
                f"{path}: generation moved during update "
                f"(loaded {loaded_generation}, saw {new_state.get('generation', 0)})")
        new_state["generation"] = loaded_generation + 1
        atomic_write_json(path, new_state)
        return new_state
