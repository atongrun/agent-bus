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
The operating recommendations in [recommended-practices.md](recommended-practices.md)
explain why the project should improve diagnostics and task-state clarity before
adding heavier queue or workflow infrastructure.

## Design Goals

1. **Robustness first**: work should not disappear on crash, disconnect, or
   handler failure.
2. **Simple deployment**: one Python service, SQLite, and systemd.
3. **Runtime-agnostic**: the server transports events. Each receiver picks
   its own local runtime (OpenCode, Claude Code, Codex CLI, scripts, etc.).
4. **Second-level responsiveness**: normal delivery should be fast, but
   millisecond latency is not a goal.
5. **Secure by default**: per-agent tokens are preferred over a shared token.
6. **CLI-first integration**: agents and humans can inspect and recover state
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
- each handler failure is recorded atomically by the server,
- events stay replayable until the configured attempt threshold moves them to
  terminal `failed`,
- terminal failures are excluded from delivery until the recipient explicitly
  requeues them.

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

## Why Not a Queue Service Yet

RabbitMQ, NATS JetStream, Redis Streams, Celery, and Temporal all provide useful
patterns: durable storage, explicit ACK, redelivery, retry limits, task state,
and observability. Agent Bus should borrow those patterns without adopting their
operational weight too early.

For the current Mac -> VPS -> Windows use case, the standard practice is:

- keep a durable single-node relay,
- ACK after successful handler completion,
- require idempotent handlers,
- expose pending/un-ACKed state,
- add clear diagnostics before adding external infrastructure.

Move to a dedicated queue or workflow engine only when there is sustained
multi-worker load, complex retry routing, many independent consumers, or
workflow state that no longer fits the SQLite relay model.

## Security Model

v0.2 supports `AGENT_BUS_AGENT_TOKENS`:

```text
architect=<token>,coder=<token>
```

In this mode:

- a token maps to one agent,
- `from_agent` must match the caller token,
- streams are limited to the caller agent,
- ACK, failure recording, failed inspection, and requeue are limited to events
  addressed to the caller agent.

## Failure Recovery

The listener reports every unsuccessful handler attempt to the server with the
event's observed `retry_count`. SQLite records the failure, increments the count,
updates `last_error`, and applies the terminal threshold in one transaction. The
observed count is an optimistic precondition: duplicate reports for the same
delivery return current state without double-counting, and a stale listener ACK
cannot overwrite a newer failure.

Before the threshold, the event returns to `pending`. At the threshold it moves
to `failed` and disappears from pending inspection and SSE delivery. The
recipient can inspect it with `agent-bus failed` and explicitly run
`agent-bus requeue EVENT_ID`. Requeue preserves `retry_count` and `last_error` as
cumulative evidence; a successful redelivery can then be ACKed normally.

This lifecycle does not claim or lease work and does not coordinate competing
consumers. Agent Bus remains a small at-least-once relay for one logical
recipient process per agent identity.

The legacy `AGENT_BUS_TOKEN` shared-token mode remains available for local
development and migration, but it should not be used for exposed deployments.

Agent Bus bearer tokens are presented on every authenticated request. For
non-local deployments, run the service behind Tailscale, HTTPS, a tunnel, or an
equivalent private transport. Public HTTP on `8800/tcp` is not a recommended
long-term deployment boundary because tokens would be sent over plaintext.

## v0.2 Non-Goals

v0.2 does not include a dashboard, kanban board, workflow DAG, enterprise IAM,
clustered database, Web UI, or replacement for GitHub issues and pull requests.
Those belong to future versions after the durable relay is proven.
