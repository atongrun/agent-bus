# Agent Bus

**Cross-machine durable event relay for AI agent collaboration.**

Agent Bus is a lightweight VPS-based event bus that lets AI agents on different machines communicate reliably. It provides durable event storage with at-least-once delivery semantics via SSE (Server-Sent Events), so no message is lost when an agent is offline.

## Architecture

```
┌──────────┐     HTTP POST /events      ┌──────────────┐     SSE /events/stream     ┌──────────┐
│  Mac     │ ──────────────────────────▶ │              │ ──────────────────────────▶ │ Windows  │
│  Codex   │                             │  Agent Bus   │                             │  OpenCode│
│ Architect│ ◀────────────────────────── │  (VPS)       │ ◀────────────────────────── │ Engineer │
└──────────┘     SSE /events/stream      │  SQLite      │     HTTP POST /events      └──────────┘
                                          └──────────────┘
              POST /events/{id}/ack ◀──────────┬──────────────────────────▶ POST /events/{id}/ack
```

- **Durable Queue**: All events are persisted to SQLite before delivery.
- **At-least-once**: Events remain `pending` until explicitly ACKed. Offline agents receive them on reconnect.
- **Simple**: Python + FastAPI + SQLite. Deploy with systemd on any Linux VPS.

## Quick Start

### 1. Server Deployment (VPS)

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus

# Install
bash scripts/install.sh

# Configure
cp .env.example .env
# Edit .env: set a strong AGENT_BUS_TOKEN

# Start
sudo systemctl start agent-bus
sudo systemctl enable agent-bus
```

### 2. Client Usage (Mac / Windows)

```bash
# Install client
pip install agent-bus

# Or from source
cd agent-bus && pip install -e .

# Configure
export AGENT_BUS_URL=http://your-vps:8800
export AGENT_BUS_TOKEN=your-secret-token
export AGENT_BUS_AGENT=coder   # or "architect"

# Send an event
agent-bus send --to coder --type task:new \
  --payload '{"url":"https://github.com/xxx/issues/12","task_id":"issue-12"}'

# Listen for events
agent-bus listen

# Future: automatic handler invocation
# agent-bus listen --on task:new "opencode run --issue {payload.task_id}"
```

## 🤖 For LLM Agents

If you are an AI agent reading this, here is how to get started:

**To install the agent-bus client on this machine:**

```
curl -s https://raw.githubusercontent.com/atongrun/agent-bus/master/docs/guide/installation.md | less
```

Read the installation guide, then configure and run:

```bash
export AGENT_BUS_URL=http://your-vps:8800
export AGENT_BUS_TOKEN=your-secret-token
export AGENT_BUS_AGENT=coder    # or "architect"

# Listen for tasks
agent-bus listen

# Send events to the other agent
agent-bus send --to architect --type pr:ready --payload '{"pr_url":"https://github.com/xxx/pull/42"}'
```

**Your role:**
- If `AGENT_BUS_AGENT=architect`: You are the architect. Plan tasks, send `task:new` events. Review PRs when you get `pr:ready`.
- If `AGENT_BUS_AGENT=coder`: You are the engineer. Listen for `task:new`, implement, submit PR, send `pr:ready`.

**Event types you should know:**
- `task:new` — architect sends a task to coder
- `task:accept` — coder confirms they're working on it
- `pr:ready` — coder submits PR for review
- `review:done` — architect finishes review

## Event Protocol

```json
{
  "id": 1,
  "from_agent": "architect",
  "to_agent": "coder",
  "type": "task:new",
  "payload": {
    "url": "https://github.com/xxx/issues/12",
    "task_id": "issue-12"
  },
  "status": "pending",
  "created_at": "2026-07-02T12:00:00Z"
}
```

### Event Types (v0.1)

| Type         | Direction          | Meaning                           |
|--------------|--------------------|-----------------------------------|
| `task:new`   | architect → coder  | New task/issue assigned           |
| `task:accept`| coder → architect  | Coder accepts the task            |
| `pr:ready`   | coder → architect  | Pull request ready for review     |
| `review:done`| architect → coder  | Review complete, feedback ready   |

## API Endpoints

| Method | Path                    | Auth   | Description                        |
|--------|-------------------------|--------|------------------------------------|
| POST   | `/events`               | Token  | Create a new event                 |
| GET    | `/events/stream?agent=` | Token  | SSE stream for an agent            |
| POST   | `/events/{id}/ack`      | Token  | Acknowledge an event               |
| GET    | `/health`               | None   | Health check                       |

All authenticated endpoints require header: `Authorization: Bearer <AGENT_BUS_TOKEN>`

## Project Structure

```
agent-bus/
├── README.md
├── pyproject.toml
├── .env.example
├── server/
│   ├── __init__.py
│   ├── main.py          # FastAPI app entry point
│   ├── db.py            # SQLite database layer
│   ├── models.py        # Pydantic models
│   ├── auth.py          # Token authentication
│   └── events.py        # Event CRUD + SSE streaming
├── client/
│   ├── __init__.py
│   └── cli.py           # CLI client (send / listen)
├── scripts/
│   ├── install.sh       # Server installation script
│   └── agent-bus.service # systemd service file
└── docs/
    ├── design.md        # Design decisions
    └── protocol.md      # Event protocol specification
```

## License

MIT
