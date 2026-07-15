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
See [docs/recommended-practices.md](docs/recommended-practices.md) for the
near-term operating stance: keep the relay lightweight, use private transport
for exposed deployments, and improve diagnostics before adding heavier
infrastructure.

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

### 1. Install

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
bash scripts/install.sh
pip install agent-bus
```

The installer creates `/etc/agent-bus/.env` with per-agent tokens:

```bash
AGENT_BUS_AGENT_TOKENS=architect=<architect-token>,coder=<coder-token>
AGENT_BUS_HOST=0.0.0.0
AGENT_BUS_PORT=8800
AGENT_BUS_DB_PATH=/opt/agent-bus/data/agent-bus.db
```

Keep port `8800` closed on the public internet unless it is protected by HTTPS,
a tunnel, or another trusted private network boundary. For local testing, use
`http://localhost:8800` as the server URL.

The recommended first production topology is:

```text
Mac Codex client -> VPS Agent Bus over Tailscale -> Windows Open Code listener
```

For this topology, the VPS Tailscale URL should work. The VPS public IP does not
need to expose `8800/tcp`.

### 2. Add and Select a Client Context

First obtain the client token by one of these paths:

- **Manual provisioning:** the first server install prints the generated
  per-agent tokens. Transfer only the matching agent token through an existing
  trusted channel, then place it in an owner-only file outside any repository,
  for example `AGENT_BUS_CODER_TOKEN=<coder-token>` in
  `~/.config/agent-bus/coder.credentials.env`.
- **Bootstrap endpoint:** when the server administrator has explicitly set
  `AGENT_BUS_BOOTSTRAP_SECRET`, exchange that provisioning secret at
  `POST /bootstrap/token`. Keep the secret in a mode-`0600` curl config so it
  does not appear in process arguments, and send the returned token directly
  to the credentials file instead of printing it:

```bash
mkdir -p ~/.config/agent-bus
chmod 700 ~/.config/agent-bus
install -m 600 /dev/null ~/.config/agent-bus/bootstrap.curl
```

Edit `bootstrap.curl` to contain:

```text
header = "X-Bootstrap-Secret: <bootstrap-secret>"
```

```bash
set -o pipefail
umask 077
credential_file="$HOME/.config/agent-bus/coder.credentials.env"
temporary_file="$(mktemp "$HOME/.config/agent-bus/.coder.credentials.env.XXXXXX")"
if curl -fsS -K ~/.config/agent-bus/bootstrap.curl \
    -H 'Content-Type: application/json' \
    --data '{"agent":"coder"}' \
    http://<private-network-host>:8800/bootstrap/token |
  python3 -c 'import json, sys; print("AGENT_BUS_CODER_TOKEN=" + json.load(sys.stdin)["token"])' \
    > "$temporary_file"
then
  chmod 600 "$temporary_file"
  mv -f "$temporary_file" "$credential_file"
else
  rm -f "$temporary_file"
  exit 1
fi
```

The bootstrap endpoint returns `404` unless enabled. Treat its secret as a
high-sensitivity provisioning credential: the current endpoint can exchange it
for any configured agent token. Use it only over Tailscale, HTTPS, or another
trusted private transport. See the
[installation guide](docs/guide/installation.md#obtaining-a-client-token) for
server setup and security details.

Now create a named connection context once. The context stores only the
credential file path and key name, never the token value:

```bash
agent-bus context add coder \
  --server http://<private-network-host>:8800 \
  --agent coder \
  --token-env AGENT_BUS_CODER_TOKEN \
  --env-file ~/.config/agent-bus/coder.credentials.env \
  --select
```

Use `--token-env NAME` without `--env-file` when the credential already exists
in the process environment. Agent Bus never stores the token value in context
JSON and never prints it from `context list`, `context show`, or `doctor`.

### 3. Diagnose and Run

```bash
agent-bus doctor
agent-bus pending
agent-bus listen --on task:new "opencode run {payload.prompt}"
```

The runtime choice remains entirely local to the receiver. Agent Bus does not
store handler commands, repository paths, Git behavior, or tool-specific
settings in a context.

To use a different context for one command without changing the selection:

```bash
agent-bus --context sender send \
  --to coder --type task:new --payload-file payload.json
```

The task is ACKed only when the handler command exits with code `0`. If the
runtime fails, times out, or the listener disconnects before ACK, the event
remains un-ACKed and replays on reconnect.

### Advanced, CI, and Compatibility

Runtime configuration precedence is:

```text
CLI flags > AGENT_BUS_* environment variables > selected context > defaults
```

CI and other headless environments can continue to use only environment
variables. Explicit flags remain available for one-off overrides:

```bash
export AGENT_BUS_URL=http://<agent-bus-host>:8800
export AGENT_BUS_TOKEN=<token>
export AGENT_BUS_AGENT=sender
agent-bus send --to receiver --type task:new --payload-file payload.json

agent-bus --url http://localhost:8800 --token <token> pending --agent receiver
```

Agent Bus does not auto-discover a repository-local `.env`. A context may read
one explicitly named env-file credential, but only the configured key.

The existing `agent-bus init` and generated `listener.env` flow remains
supported for Agent Workflow/OpenCode listener compatibility. Existing users
can continue to `source ~/.config/agent-bus/listener.env` and run `agent-bus
doctor --listener`; new normal client setups should prefer contexts. See the
[installation guide](docs/guide/installation.md#legacy-listenerenv-compatibility).

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
agent-bus pending
agent-bus ack 42
agent-bus listen --once --on task:new "echo {payload.task_id}"
agent-bus context list
agent-bus context show
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
- Workflow memory or prompt-context management
- Dashboard or Web UI
- Any tool-specific logic (OpenCode, Claude Code, Codex CLI, Hermes, etc.)

These belong in your Worker Runtime, not in the relay.

## Development

```bash
bash scripts/test.sh
```

The test script requires Python 3.11+ and `uv`.
