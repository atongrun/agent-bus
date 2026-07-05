# Agent Bus

**A lightweight, durable, cross-machine communication and invocation layer for AI agents.**

> **Agent Bus is not an AI coding agent. It does not execute tasks itself.**  
> It transports task events between agents—reliably, securely, and across
> machines—and lets each receiving endpoint invoke its own local runtime
> (OpenCode, Claude Code, Codex CLI, a shell script, a test runner, or any
> other tool).

Agent Bus fills the gap that plain HTTP calls, shell pipes, and Git-based
polling leave open: durable event relay with explicit ACK, recoverable handoff
after disconnects, and role-based addressing (`to=coder`, `to=reviewer`).

## What Agent Bus Is

| Is | Is Not |
|----|--------|
| A cross-machine event relay with at-least-once delivery | An AI coding agent or LLM runner |
| A role-based invocation layer (`architect → coder`, `coder → reviewer`) | A workflow engine or DAG orchestrator |
| Runtime-agnostic: the receiver picks its own tool (OpenCode, Claude Code, Codex CLI, script, etc.) | An OpenCode plugin or Codex-specific tool |
| Durable: events survive crashes, disconnects, and handler failures | A dashboard, kanban board, or Web UI |
| Small: Python, FastAPI, SQLite, SSE, CLI — deployable on a cheap VPS in minutes | An agent framework or multi-agent platform |

In short: **Agent Bus is closer to a small "Agent RTE"** — it handles addressing,
decoupling, and reliable transport. Each connected agent is responsible for its
own planning, execution, review, and memory.

## Architecture

```
Architect / Planner Agent
        │
        │  POST /events   (HTTP)
        ▼
 ┌──────────────┐     SSE /events/stream     ┌─────────────────────┐
 │              │ ──────────────────────────▶ │                     │
 │  Agent Bus   │                             │  Worker Runtime     │
 │  (VPS)       │ ◀────────────────────────── │                     │
 │  SQLite      │     POST /events  (HTTP)    │  ┌───────────────┐  │
 │              │                             │  │ OpenCode       │  │
 └──────────────┘                             │  │ Claude Code    │  │
                                              │  │ Codex CLI      │  │
                                              │  │ shell script   │  │
                                              │  │ test runner    │  │
                                              │  └───────────────┘  │
                                              └─────────────────────┘
```

- **Durable queue**: events are persisted in SQLite before delivery.
- **At-least-once delivery**: un-ACKed events replay after reconnect.
- **Handler-success ACK**: listener handlers ACK only after the invoked command exits with code `0`.
- **Agent-scoped tokens**: each agent can send, stream, and ACK only within its own scope.

### Concrete example

```
Mac (architect, Codex)  →  VPS Agent Bus  →  Windows (coder, OpenCode)
```

This is one specific configuration. The same relay works with Claude Code on
Linux, Codex CLI on macOS, a verification script on localhost, or any
combination of agents across your machines.

## Quick Start

### 1. Deploy the Server

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

For local testing, set `AGENT_BUS_URL=http://localhost:8800`.

### 2. Planner / Architect Side

The planner creates task events and listens for completion notifications.

```bash
export AGENT_BUS_URL=http://your-server:8800
export AGENT_BUS_TOKEN=<architect-token>
export AGENT_BUS_AGENT=architect

# Dispatch a task to the worker
agent-bus send --to coder --type task:new --payload '{
  "task_id": "task-001",
  "title": "Implement the issue",
  "prompt": "Read the linked issue, implement it, test it, and open a PR.",
  "url": "https://github.com/example/repo/issues/1"
}'

# Listen for the result the worker sends back
agent-bus listen --agent architect --on pr:ready "codex review --pr {payload.pr_url}"
```

### 3. Worker / Executor Side

The worker listens for incoming tasks and invokes its local runtime.  
**OpenCode is one possible runtime. You can use Claude Code, Codex CLI, a shell
script, or anything that accepts a command-line prompt.**

```bash
export AGENT_BUS_URL=http://your-server:8800
export AGENT_BUS_TOKEN=<coder-token>
export AGENT_BUS_AGENT=coder

# OpenCode example
agent-bus listen --agent coder --on task:new "opencode run {payload.prompt}"

# Claude Code example
agent-bus listen --agent coder --on task:new "claude --print '{payload.prompt}'"

# Codex CLI example
agent-bus listen --agent coder --on task:new "codex exec '{payload.prompt}'"

# Generic script example
agent-bus listen --agent coder --on task:new "bash run-task.sh {payload.task_id} '{payload.prompt}'"
```

The task is ACKed only when the handler command exits with code `0`. If the
runtime fails, times out, or the listener disconnects before ACK, the event
remains un-ACKed and replays on reconnect.

### 4. Same-Machine Agents

The protocol works identically across agents on the same machine:

```bash
export AGENT_BUS_URL=http://localhost:8800
agent-bus listen --agent verifier --on task:new "python verify.py {payload.task_id}"
```

## Event Protocol

Recommended event types (conventions, not enforced schema):

| Type | Typical direction | Suggested payload |
|------|-------------------|-------------------|
| `task:new` | planner → worker | `task_id`, `title`, `prompt`, `repo`, `branch`, `url` |
| `task:accept` | worker → planner | `task_id`, `message` |
| `task:failed` | worker → planner | `task_id`, `exit_code`, `summary` |
| `pr:ready` | worker → planner | `task_id`, `pr_url`, `summary` |
| `review:done` | planner → worker | `task_id`, `status`, `summary` |

- `pr:ready` is an example from a GitHub coding workflow. For non-GitHub
  workflows, `task:completed` with `artifact_uri` / `artifact_type` is a
  reasonable alternative.
- Payloads are free-form JSON. These fields are recommended for
  interoperability but not validated server-side.
- You can add custom types (`deploy:done`, `test:passed`, etc.) at any time.

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

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/events` | Agent token | Create an event |
| GET | `/events/pending?agent=` | Agent token | List un-ACKed events |
| GET | `/events/stream?agent=` | Agent token | SSE stream |
| POST | `/events/{id}/ack` | Agent token | ACK an event |
| GET | `/health` | None | Health check |

All authenticated endpoints use `Authorization: Bearer <AGENT_BUS_TOKEN>`.

## Scope & Boundaries

**Agent Bus is deliberately small and does one thing well: reliable agent-to-agent event transport.**

It is **not** a workflow engine, a dashboard, an agent framework, or an
AI runtime. Think of it as a small "Agent RTE" — it handles addressing,
decoupling, and reliable transport between agents. Each connected agent
handles its own planning, execution, review, and memory.

- No dashboard or Web UI.
- No DAG orchestration or workflow engine.
- No built-in AI execution, RAG, or LLM calls.
- No agent marketplace or plugin registry.
- No replacement for GitHub Issues, PRs, or CI.

For the longer-term direction (task boards, workflow orchestration, human
gates), see [docs/vision.md](docs/vision.md). Those are future goals — the
v0.2 scope stays focused on durable event relay.

## Development

```bash
bash scripts/test.sh
```

The test script requires Python 3.10+ and the dependencies listed in
`pyproject.toml`.
