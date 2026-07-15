# Packet Lab

Packet Lab is a long-term educational project.

Its purpose is **not** to build a packet analyzer.

Its purpose is to become an expert systems engineer by understanding how computers communicate, from the network card up to HTTP, by observing real packets on a real Linux machine and building small tools to investigate them.

The packet viewer is only a learning instrument.

The networking concepts are the real product.

## Philosophy

Every protocol is learned in the following order:

1. Theory
2. Observe it on Linux
3. Predict what should happen
4. Run the experiment
5. Explain the observed behaviour
6. Build only enough tooling to make the observation easier
7. Reflect

The student prefers understanding over speed.

The project intentionally avoids hiding concepts behind large frameworks or "magic" libraries.

First time here? See `docs/SETUP.md` for environment setup (prerequisites, capture permissions, first run) before starting a lesson.

## Student Commands

Say these to the assistant at any time. They keep every lesson on-scope and
drift-free — no repository knowledge needed. (The assistant-side rules backing
them live in `AGENTS.md` under **Pacing**.)

| Command | What it does |
|---|---|
| `resume lesson` | Start a session: the assistant reads all project docs, summarizes progress, states today's objective and its exact scope, then asks one warm-up question. |
| `scope?` | Ask for tonight's step list at any moment. Anything the assistant does outside that list is drift — call it out with one word. |
| `go ahead` / `move on` | Skip a question or discussion instantly. The assistant complies in the same message, no re-arguing. |
| `curiosity` | Take a short detour on a side question. One complete answer, then straight back to the roadmap. |
| `quiz me` | Get a conceptual quiz on what's been learned (reasoning over memorization). |
| `end lesson for today` | Wrap up: lesson archived, knowledge distilled, next milestone written, health-checked, committed and pushed — automatically, no confirmations. |
| `reset progress` | Wipe all recorded progress and restart the whole 12-version program from Version 1. Asks for confirmation first, since it archives lesson history — unlike the other automatic commands. |

Standing guarantees the assistant must honor:

- One question per concept, maximum.
- The milestone closes the moment its Definition of Done is met — you should
  never need to ask.
- Settled design decisions are never reopened unless you reopen them.