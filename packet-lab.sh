#!/usr/bin/env bash
#
# packet-lab.sh — single entry point for the Packet Lab control plane.
#
# This is a thin passthrough to `python3 -m packetlab.lab`, plus a dependency
# check and a couple of convenience aliases. All real logic lives in Python so
# there is never a second command surface to drift out of sync.
#
#   ./packet-lab.sh doctor            # docs + curriculum/ROADMAP consistency
#   ./packet-lab.sh test              # unit tests (safety mechanisms)
#   ./packet-lab.sh eval              # control-plane conformance evals
#   ./packet-lab.sh demo [--failure]  # scripted end-to-end run
#   ./packet-lab.sh viewer [mode] [iface]   # the live packet viewer
#   ./packet-lab.sh lesson start v3.0 # lesson lifecycle (see: lab --help)
#   ./packet-lab.sh <anything else>   # forwarded to python3 -m packetlab.lab
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing dependency: $1" >&2; exit 1; }
}

need python3

case "${1:-help}" in
  test)
    exec python3 -m unittest discover -s tests "${@:2}"
    ;;
  close|end)
    # Forgiving aliases for the proportional session close.
    exec python3 -m packetlab.lab lesson end "${@:2}"
    ;;
  viewer)
    shift
    exec python3 scripts/packetlab.py "$@"
    ;;
  help|-h|--help|"")
    cat <<'USAGE'
Packet Lab — a goal-controlled agentic tutor for Linux networking.

Common commands:
  ./packet-lab.sh doctor              health check (doc caps + state consistency)
  ./packet-lab.sh test                run the safety-mechanism unit tests
  ./packet-lab.sh eval                run control-plane conformance evals
  ./packet-lab.sh demo [--failure]    scripted end-to-end run (real execution)
  ./packet-lab.sh viewer [mode] [if]  the live tcpdump-backed packet viewer
  ./packet-lab.sh resume              fast read-only resume snapshot
  ./packet-lab.sh lesson start v3.0   begin a lesson session
  ./packet-lab.sh close --reason "…"  proportional session close (lesson end)
  ./packet-lab.sh inspect <run-id>    inspect a run trace (--verify, --timeline)

Everything else is forwarded to `python3 -m packetlab.lab`. Run it with
--help for the full command reference.
USAGE
    ;;
  *)
    exec python3 -m packetlab.lab "$@"
    ;;
esac
