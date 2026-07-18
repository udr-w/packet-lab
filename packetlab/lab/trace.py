"""Structured, hash-chained run traces.

A run is one lesson session. `lesson start` mints a run id and every later
CLI invocation in that session appends events to
state/runs/<run-id>/trace.jsonl — one JSON object per line, so a crash loses
at most the line being written.

Each event carries the SHA-256 of the previous event, forming a chain. The
chain is what makes the trace an audit record rather than a diary: because the
tutoring agent has repo write access, it *could* edit state files directly,
but `inspect --verify` recomputes the chain and cross-checks that every
governor-guarded state change has a matching trace event. A silent edit breaks
the chain or leaves an unbacked state mutation, and the verifier flags it. See
docs/threat-model.md — the boundary is physical for generated tools and
guarded subprocesses, and audit-detectable (not physically blocked) for the
agent itself. That distinction is stated plainly, never papered over.

Traces store summaries, not payloads: long fields are truncated and packet
payloads / file contents are never emitted here. Captures live in capture/
and are gitignored.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets

from packetlab.lab.statefile import state_lock

TRUNCATE_AT = 2_000
GENESIS_HASH = "0" * 64


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runs_dir(base_dir: Path | None = None) -> Path:
    """The directory holding run subdirectories.

    ``base_dir`` is a learner's state directory (state/learners/<id>), giving
    per-learner trace isolation. It defaults to the global state dir only for
    backward compatibility; the CLI always passes a learner directory.
    """
    return (base_dir or (repo_root() / "state")) / "runs"


def new_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{secrets.token_hex(3)}"


def _truncate(value):
    if isinstance(value, str) and len(value) > TRUNCATE_AT:
        return value[:TRUNCATE_AT] + "...[truncated]"
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value[:100]]
    return value


def _hash_event(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Trace:
    """Append-only, hash-chained JSONL event stream for one run.

    Every event carries the learner id so trace inspection always shows which
    learner's context a run belongs to, and one learner's chain verifies
    independently of another's.
    """

    def __init__(self, run_id: str, lesson_id: str | None,
                 base_dir: Path | None = None, learner_id: str | None = None) -> None:
        self.run_id = run_id
        self.lesson_id = lesson_id
        self.learner_id = learner_id
        self.dir = runs_dir(base_dir) / run_id
        self.path = self.dir / "trace.jsonl"

    def emit(self, component: str, event: str, **fields) -> dict:
        """Append one chained event. Returns the record written.

        The read-of-tail and append happen under the run's lock so two
        concurrent CLI processes cannot fork the chain or collide on seq.
        """
        with state_lock(self.dir):
            events = read_trace(self.path)
            seq = len(events)
            prev_hash = events[-1]["this_hash"] if events else GENESIS_HASH
            record = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "run_id": self.run_id,
                "lesson_id": self.lesson_id,
                "learner_id": self.learner_id,
                "seq": seq,
                "component": component,
                "event": event,
                "prev_hash": prev_hash,
            }
            for key, value in fields.items():
                if key in record or key == "this_hash":
                    continue
                record[key] = _truncate(value)
            record["this_hash"] = _hash_event(record)
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                handle.flush()
        return record

    @staticmethod
    def open_existing(run_id: str, base_dir: Path | None = None) -> "Trace":
        lesson_id = None
        learner_id = None
        events = read_trace(runs_dir(base_dir) / run_id / "trace.jsonl")
        if events:
            lesson_id = events[0].get("lesson_id")
            learner_id = events[0].get("learner_id")
        return Trace(run_id, lesson_id, base_dir=base_dir, learner_id=learner_id)


def read_trace(path: Path) -> list[dict]:
    """Load a trace. Malformed lines become parse-error stubs, never hidden."""
    events: list[dict] = []
    if not path.exists():
        return events
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line, parse_constant=_reject))
            except (ValueError, json.JSONDecodeError):
                events.append({"event": "trace_parse_error", "line": line_no,
                               "component": "trace", "raw": line[:200]})
    return events


def _reject(value):
    raise ValueError("forbidden JSON constant")


def verify_chain(path: Path) -> tuple[bool, list[str]]:
    """Recompute the hash chain. Returns (ok, list of problems)."""
    problems: list[str] = []
    events = read_trace(path)
    prev = GENESIS_HASH
    for event in events:
        if event.get("event") == "trace_parse_error":
            problems.append(f"seq ?: unparseable line {event.get('line')}")
            return False, problems
        stored = event.get("this_hash")
        recomputed = _hash_event({k: v for k, v in event.items() if k != "this_hash"})
        if event.get("prev_hash") != prev:
            problems.append(f"seq {event.get('seq')}: prev_hash breaks the chain")
        if stored != recomputed:
            problems.append(f"seq {event.get('seq')}: this_hash does not match content")
        prev = stored or recomputed
    return not problems, problems


def list_runs(base_dir: Path | None = None) -> list[str]:
    directory = runs_dir(base_dir)
    if not directory.is_dir():
        return []
    return sorted(entry.name for entry in directory.iterdir()
                  if entry.is_dir() and (entry / "trace.jsonl").exists())
