# Agent Bus

**Lightweight durable event relay for local and remote AI agent collaboration.**

Agent Bus lets agents on different machines, or multiple agents on the same
machine, exchange durable task events. It is intentionally small: Python,
FastAPI, SQLite, SSE, and CLI commands. The design target is second-level
responsiveness, strong recoverability, and simple deployment on a VPS or
localhost.

See [docs/vision.md](docs/vision.md) for the longer-term direction: task boards,
workflow orchestration, human gates, and richer multi-agent coordination are
future goals, not v0.2 scope.

## Architecture

```
┌──────────┐     HTTP POST /events      ┌──────────────┐     SSE /events/stream     ┌──────────┐
│  Mac     │ ──────────────────────────▶ │              │ ──────────────────────────▶ │ Windows  │
│  Codex   │                             │  Agent Bus   │                             │ Open Code│
│Architect │ ◀────────────────────────── │  SQLite      │ ◀────────────────────────── │ Engineer │
└──────────┘     SSE /events/stream      └──────────────┘     HTTP POST /events      └──────────┘
```

- **Durable queue**: events are persisted before delivery.
- **At-least-once delivery**: un-ACKed events replay after reconnect.
- **Handler-success ACK**: listener handlers ACK only after successful command exit.
- **Agent-scoped tokens**: each agent can send, stream, and ACK only within its own scope.

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

For local testing, use `AGENT_BUS_URL=http://localhost:8800`.

### 2. Mac Codex Side

```bash
export AGENT_BUS_URL=http://your-vps:8800
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

### 3. Windows Open Code Side

Run the listener in a foreground terminal first. This keeps v0.2 easy to debug.

PowerShell:

```powershell
$env:AGENT_BUS_URL = "http://your-vps:8800"
$env:AGENT_BUS_TOKEN = "<coder-token>"
$env:AGENT_BUS_AGENT = "coder"

agent-bus listen --agent coder --on task:new "opencode run --prompt {payload.prompt}"
```

The task is ACKed only when the command exits with code `0`. If Open Code fails,
times out, or the listener disconnects before ACK, the event remains un-ACKed
and is replayed later.

### 4. Same-Machine Agents

The same protocol works locally:

```bash
export AGENT_BUS_URL=http://localhost:8800
agent-bus listen --agent verifier --on task:new "python verify.py {payload.task_id}"
```

## Useful CLI Commands

```bash
agent-bus send --to coder --type task:new --payload-file payload.json
agent-bus pending --agent coder
agent-bus ack 42
agent-bus listen --agent coder --once --on task:new "echo {payload.task_id}"
```

Handler templates can reference event fields:

- `{id}`
- `{type}`
- `{from_agent}`
- `{to_agent}`
- `{payload.task_id}`
- `{payload.title}`
- `{payload.prompt}`
- `{payload.url}`

## Event Protocol

Recommended v0.2 event types:

| Type | Direction | Suggested payload |
| --- | --- | --- |
| `task:new` | architect -> coder | `task_id`, `title`, `prompt`, `repo`, `branch`, `url` |
| `task:accept` | coder -> architect | `task_id`, `message` |
| `task:failed` | coder -> architect | `task_id`, `exit_code`, `summary` |
| `pr:ready` | coder -> architect | `task_id`, `pr_url`, `summary` |
| `review:done` | architect -> coder | `task_id`, `status`, `summary` |

Payloads are conventions, not strict server-side schemas.

## API Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/events` | Agent token | Create an event |
| GET | `/events/pending?agent=` | Agent token | List un-ACKed events |
| GET | `/events/stream?agent=` | Agent token | SSE stream |
| POST | `/events/{id}/ack` | Agent token | ACK an event |
| GET | `/health` | None | Health check |

All authenticated endpoints use:

```text
Authorization: Bearer <AGENT_BUS_TOKEN>
```

## Development

```bash
bash scripts/test.sh
```

The test script requires Python 3.11+ and `uv`.
