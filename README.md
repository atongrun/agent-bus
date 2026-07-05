# Agent Bus

**Lightweight durable event relay for local and remote AI agent collaboration.**

Agent Bus lets agents on different machines, or multiple agents on the same
machine, exchange durable task events. It is intentionally small: Python,
FastAPI, SQLite, SSE, and CLI commands. The design target is second-level
responsiveness, strong recoverability, and simple deployment on a VPS or
localhost.

Agent Bus is **runtime-agnostic**: it transports events between agent
endpoints. Each receiving endpoint decides which local tool to invoke —
OpenCode, Claude Code, Codex CLI, a shell script, or anything that accepts a
command-line prompt. Agent Bus does not execute AI tasks, manage Git repos, or
orchestrate workflows. See [docs/worker.md](docs/worker.md) for how Worker
Runtimes bridge Agent Bus to local tools.

See [docs/product-positioning.md](docs/product-positioning.md) for the product
boundary and [docs/roadmap.md](docs/roadmap.md) for the staged roadmap. The
short version: durable messaging first, Worker Adapter examples second, desktop
or tray UI later, and no workflow engine in the core relay.

## Architecture

```
┌──────────────────┐                         ┌──────────────────────┐
│ Any Agent        │                         │ Worker Runtime       │
│ Sender / Planner │                         │ Receiver / Adapter   │
│ Human / Script   │                         │                      │
│                  │   HTTP POST /events     │   SSE /events/stream │  ┌───────────────┐
│  ┌────────────┐  │ ──────────────────────▶ │ ┌──────────────────┐ │  │ OpenCode      │
│  │ agent-bus  │  │                         │ │ agent-bus listen │─┼─▶│ Claude Code   │
│  │ send       │  │       ┌──────────┐      │ │ --on task:new    │ │  │ Codex CLI     │
│  └────────────┘  │       │          │      │ └──────────────────┘ │  │ shell script  │
│                  │ ◀──── │Agent Bus │ ──── │                      │  └───────────────┘
│  ┌────────────┐  │       │ SQLite   │      │ ┌──────────────────┐ │
│  │ agent-bus  │  │       │          │      │ │ agent-bus send   │ │
│  │ listen     │◀─┼───────└──────────┘      │ │ (report result)  │ │
│  └────────────┘  │  SSE /events/stream     │ └──────────────────┘ │
└──────────────────┘                         └──────────────────────┘
      events flow in both directions (HTTP POST + SSE)
```

- **Durable queue**: events are persisted before delivery.
- **At-least-once delivery**: un-ACKed events replay after reconnect.
- **Handler-success ACK**: listener handlers ACK only after successful command exit.
- **Agent-scoped tokens**: each agent can send, stream, and ACK only within its own scope.

### Roles Are Conventions, Not Identities

Agent Bus does not hardcode `architect`, `coder`, or `reviewer`. These are
**role labels** adopted by a particular workflow. Any agent can send events.
Any agent can receive them. A single agent can be the sender in one exchange
and the receiver in the next. See [docs/worker.md](docs/worker.md).

## Quick Start

### 1. Server on a VPS or Localhost

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
bash scripts/install.sh
```

The installer creates `/etc/agent-bus/.env` with per-agent tokens:

```bash
AGENT_BUS_AGENT_TOKENS=architect=<architect-token>,coder=<coder-token>
AGENT_BUS_HOST=0.0.0.0
AGENT_BUS_PORT=8800
AGENT_BUS_DB_PATH=/opt/agent-bus/data/agent-bus.db
```

For a VPS, prefer private-network access such as Tailscale:

```bash
export AGENT_BUS_URL=http://<vps-tailscale-ip>:8800
```

Keep port `8800` closed on the public internet unless it is protected by HTTPS,
a tunnel, or another trusted private network boundary. For local testing, use
`AGENT_BUS_URL=http://localhost:8800`.

### 2. Sender Side (Planner / Architect)

Any agent that wants to dispatch a task. The sender does not need to know
which tool the receiver will use.

```bash
export AGENT_BUS_URL=http://<agent-bus-host>:8800
export AGENT_BUS_TOKEN=<architect-token>
export AGENT_BUS_AGENT=architect

agent-bus send --to coder --type task:new --payload '{
  "task_id": "task-001",
  "title": "Implement the issue",
  "prompt": "Read the linked issue, implement it, test it, and open a PR.",
  "url": "https://github.com/example/repo/issues/1"
}'

agent-bus listen --agent architect --on pr:ready "echo PR ready: {payload.pr_url}"
```

### 3. Receiver Side (Worker / Executor)

The receiver runs `agent-bus listen` with a `--on` handler that invokes its
local runtime. **The runtime choice is entirely up to the receiver.** Agent Bus
has no opinion about which tool you use.

```bash
export AGENT_BUS_URL=http://<agent-bus-host>:8800
export AGENT_BUS_TOKEN=<coder-token>
export AGENT_BUS_AGENT=coder

# OpenCode — one possible runtime
agent-bus listen --agent coder --on task:new "opencode run {payload.prompt}"

# Claude Code — another possible runtime
agent-bus listen --agent coder --on task:new "claude --print '{payload.prompt}'"

# Codex CLI — yet another
agent-bus listen --agent coder --on task:new "codex exec '{payload.prompt}'"
```

The task is ACKed only when the handler command exits with code `0`. If the
runtime fails, times out, or the listener disconnects before ACK, the event
remains un-ACKed and replays on reconnect.

### 4. Same-Machine Agents

The same protocol works locally:

```bash
export AGENT_BUS_URL=http://localhost:8800
agent-bus listen --agent verifier --on task:new "python verify.py {payload.task_id}"
```

## Worker Runtime / Adapter

A **Worker Runtime** is the thin shell between Agent Bus and the local tool
that does the actual work. It is **not part of Agent Bus** — it is an example
of what an endpoint can build on top of the event relay.

```
Worker Runtime lifecycle:
  receive task:new → prepare workspace → invoke local tool → report result
```

See [`docs/worker.md`](docs/worker.md) for the full design. See
[`examples/`](examples/) for reference implementations (OpenCode, generic).

| Concern | Agent Bus | Worker Runtime |
|---------|:---------:|:--------------:|
| Event transport | ✅ | — |
| Git operations | — | ✅ |
| AI execution | — | ✅ |
| Test running | — | ✅ |
| Workspace management | — | ✅ |
| Commit / push / PR | — | ✅ |

## Useful CLI Commands

```bash
agent-bus send --to coder --type task:new --payload-file payload.json
agent-bus pending --agent coder
agent-bus ack 42
agent-bus listen --agent coder --once --on task:new "echo {payload.task_id}"
```

Handler templates can reference event fields:

- `{id}`, `{type}`, `{from_agent}`, `{to_agent}`
- `{payload.task_id}`, `{payload.title}`, `{payload.prompt}`, `{payload.url}`

## Event Protocol

Recommended event types (conventions, not enforced schema):

| Type | Typical direction | Suggested payload |
|------|-------------------|-------------------|
| `task:new` | sender → receiver | `task_id`, `title`, `prompt`, `repo`, `branch`, `url` |
| `task:accept` | receiver → sender | `task_id`, `message` |
| `task:failed` | receiver → sender | `task_id`, `exit_code`, `summary` |
| `pr:ready` | receiver → sender | `task_id`, `pr_url`, `summary` |
| `review:done` | sender → receiver | `task_id`, `status`, `summary` |

Payloads are free-form JSON. The direction labels (`sender → receiver`) are
workflow conventions, not protocol constraints. Any agent can send any event
type.  `pr:ready` is a GitHub coding workflow example; for non-GitHub
workflows, `task:completed` with `artifact_uri` is a reasonable alternative.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/events` | Agent token | Create an event |
| GET | `/events/pending?agent=` | Agent token | List un-ACKed events |
| GET | `/events/stream?agent=` | Agent token | SSE stream |
| POST | `/events/{id}/ack` | Agent token | ACK an event |
| GET | `/health` | None | Health check |

All authenticated endpoints use `Authorization: Bearer <AGENT_BUS_TOKEN>`.
Bearer tokens are sent with each request. Use Tailscale, HTTPS, or another
trusted private transport for any non-local deployment.

## What Agent Bus Does NOT Provide

- Git operations (clone, checkout, commit, push)
- AI model invocation or prompt construction
- Workflow DAG or orchestration
- Agent selection or routing strategy
- Memory or context management
- Dashboard or Web UI
- Any tool-specific logic (OpenCode, Claude Code, Codex CLI, Hermes, etc.)

These belong in your Worker Runtime, not in the relay.

## Development

```bash
bash scripts/test.sh
```

The test script requires Python 3.11+ and `uv`.
