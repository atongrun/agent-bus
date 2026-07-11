# Agent Bus — Brownfield Baseline

> Artifact: Baseline | Role: architect/planner (Claude Code) | Date: 2026-07-11
> Method: Agent Workflow (constitution.md §3 Brownfield). Evidence-based — every
> "verified" claim below was confirmed by running the code, not by reading docs.

## What this project is

Agent Bus is a **lightweight, runtime-agnostic, durable event relay** for AI agents to
hand off work across machines. FastAPI + SQLite + SSE. It deliberately does **not** do
Git, AI invocation, workflow orchestration, or routing — those belong to external Worker
Runtimes. (README.md; `docs/product-positioning.md`.)

## Verified capabilities (confirmed by execution)

- ✅ **Unit tests pass**: `10 tests ... OK` via `.venv/bin/python -m unittest discover -s tests`.
- ✅ **Server runs**: FastAPI on `server.main:app`; `/health` returns `{"status":"ok"}`.
- ✅ **Real end-to-end over the user's VPS** ($AGENT_BUS_URL, per-agent tokens):
  `architect send task` → VPS relays + persists → **local coder listener** receives →
  handler launches **local OpenCode (glm-5.2)** → OpenCode parses `{payload.task_id}`
  and writes the marker file `OPENCODE_RAN AWF-E2E-132537` → event ACK'd → queue empty.
- ✅ **Durable queue + at-least-once**: a stale 2026-07-05 event was still replayed on
  reconnect (persisted, un-ACKed) until explicitly ACK'd.
- ✅ **Per-agent tokens**: architect token cannot list coder's pending (403); coder token
  works for coder. Auth isolation is real.
- ✅ **Handler-success ACK**: listener ACKs only when the handler exits 0 (`client/cli.py:283`).

## Current architecture (as-is)

- `server/`: `main.py` (app+health), `events.py` (POST /events, GET /events/pending,
  GET /events/stream SSE, POST /events/{id}/ack), `auth.py` (per-agent + legacy token),
  `db.py` (SQLite WAL), `models.py` (Pydantic).
- `client/cli.py`: `agent-bus send | listen | pending | ack`. Listener runs shell handlers
  with `{payload.*}` template rendering; reconnect w/ exponential backoff.
- Deploy: systemd on Ubuntu VPS, `/etc/agent-bus/.env`, Tailscale-only (public 8800 closed).
- Tests: `tests/test_auth.py` (4), `tests/test_cli_helpers.py` (6). No HTTP/SSE e2e unit test.

## Accepted constraints / boundaries (do NOT change)

- Stays a **relay**, not an orchestrator. No Git/AI/DAG/routing in the core.
- Single-node SQLite + SSE. No clustering, no external broker.
- Runtime-agnostic: knows nothing about OpenCode/Claude/Codex.
- Python >=3.10 on the VPS (not 3.11 — see deploy memory).

## Problems found in real use (this session)

| # | Problem | Evidence |
|---|---------|----------|
| P1 | **No diagnostics.** Setup/troubleshooting is all manual SSH+curl. Couldn't tell where token/config lived without probing. | Whole session; `docs/recommended-practices.md:36-48` calls `doctor` the top near-term need. |
| P2 | **Broadcast, not a work queue.** Two same-name workers (e.g. mac+windows both `coder`) would BOTH receive/run the same task — no lease/claim. | `server/events.py:126-158` (SSE replays all pending to every connection). |
| P3 | **No graceful/remote exit.** Listener only exits via `--once` or Ctrl+C. It does NOT follow the parent tool's exit and has no remote "shutdown" signal. | `client/cli.py:302-357`. |
| P4 | **Stale events clog the queue.** An un-ACKed event replays forever; `--once` collides with it. No TTL/expiry. | The 2026-07-05 `win-poll-smoke` event blocked our first run. |

## Next milestone (chosen by user)

**M1: `agent-bus doctor` self-check command.** Lowest risk, non-invasive, directly reduces
human involvement (addresses P1). Roadmap already ranks it as the most important near-term
improvement. P2/P3/P4 are recorded as `Later` and do **not** block M1.

## Test evidence commands (reproducible)

```bash
cd <agent-bus-repo>
.venv/bin/python -m unittest discover -s tests      # 10 tests OK
.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 18899  # /health ok
```

## Execution setup for this workflow run (confirmed working)

- Executor = **local OpenCode** (`/opt/homebrew/bin/opencode` v1.17.13, `opencode run "<prompt>"`).
- Cross-machine execution is **out of scope** for this project run (user: "下个项目跨机器做").
