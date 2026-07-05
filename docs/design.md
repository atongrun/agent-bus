# Agent Bus Design

Agent Bus is a small, durable event relay for AI agent collaboration. Its
primary job is reliable cross-machine handoff: a sender dispatches tasks, a
receiver picks them up and executes them locally, and results flow back over
the same relay.

Codex on macOS handing work to OpenCode on Windows is one concrete example.
The same design works with Claude Code on Linux, Codex CLI on macOS, a shell
script on any machine, or multiple agents on a single localhost. See
[docs/worker.md](worker.md) for how Worker Runtimes bridge Agent Bus to local
tools.

The long-term direction is described in [vision.md](vision.md). This design
keeps v0.2 intentionally narrow so the relay stays reliable and easy to deploy.

## Design Goals

1. **Robustness first**: work should not disappear on crash, disconnect, or
   handler failure.
2. **Simple deployment**: one Python service, SQLite, and systemd.
3. **Runtime-agnostic**: the server transports events. Each receiver picks
   its own local runtime (OpenCode, Claude Code, Codex CLI, scripts, etc.).
4. **Second-level responsiveness**: normal delivery should be fast, but
   millisecond latency is not a goal.
4. **Secure by default**: per-agent tokens are preferred over a shared token.
5. **CLI-first integration**: agents and humans can inspect and recover state
   without a dashboard.

## Current Architecture

Clients create events with HTTP `POST /events`. Recipients receive events
through `GET /events/stream?agent=...` using SSE. Events remain in SQLite until
the recipient explicitly calls `POST /events/{id}/ack`.

```
[Agent A] --POST /events--> [Agent Bus + SQLite] --SSE--> [Agent B handler]
    ^                                |                         |
    |                                +---- un-ACKed replay ----+
    +---------- POST /events/{id}/ack after success -----------+
```

## Delivery Semantics

Agent Bus uses at-least-once delivery:

- events are persisted before delivery,
- pending and delivered events replay after reconnect,
- listeners ACK only after successful processing,
- handlers that fail or time out leave events un-ACKed.

This means handlers must be idempotent or tolerate duplicate execution. The
event `id` and recommended `payload.task_id` are available for deduplication.

## Why SSE

SSE is enough because clients send events through normal HTTP POST and only need
server-to-client push for delivery. It is simpler than WebSocket, works well
through standard HTTP proxies, and reconnects cleanly. The server polls SQLite
every 500 ms for new events, which fits the second-level latency goal.

## Why SQLite

SQLite keeps deployment small and operationally boring. WAL mode is sufficient
for a few agents and low event volume. External databases or queue systems are
future options only if the project outgrows the simple single-node model.

## Security Model

v0.2 supports `AGENT_BUS_AGENT_TOKENS`:

```text
architect=<token>,coder=<token>
```

In this mode:

- a token maps to one agent,
- `from_agent` must match the caller token,
- streams are limited to the caller agent,
- ACK is limited to events addressed to the caller agent.

The legacy `AGENT_BUS_TOKEN` shared-token mode remains available for local
development and migration, but it should not be used for exposed deployments.

## v0.2 Non-Goals

v0.2 does not include a dashboard, kanban board, workflow DAG, enterprise IAM,
clustered database, Web UI, or replacement for GitHub issues and pull requests.
Those belong to future versions after the durable relay is proven.
