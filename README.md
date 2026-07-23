# Agent Bus

Lightweight durable event relay for agents running on the same machine or
across a small set of trusted machines.

Agent Bus accepts events over HTTP, persists them in SQLite, and delivers them
to the recipient over Server-Sent Events (SSE). A receiving process decides
what to do with each event and acknowledges it after successful handling.

```text
Sender / Planner
       |
       | POST event
       v
 Agent Bus Server
  FastAPI + SQLite
       |
       | SSE
       v
Receiver / Worker Adapter
       |
       v
OpenCode / Claude Code / Codex / Script
```

Agent Bus is the reliable transport in this diagram. The Worker Runtime or
adapter prepares workspaces, invokes local tools, runs tests, and reports
results. That runtime is not part of Agent Bus Core; the files under
[`examples/`](examples/) are reference implementations, not a production
workflow system.

## Why Agent Bus

Agent-to-agent handoffs are easy to lose when machines disconnect or a local
tool fails. Agent Bus provides a small inspectable relay for low-volume
collaboration between trusted endpoints without introducing a full workflow
platform or external queue service.

The current stack is Python 3.11+, FastAPI, SQLite, SSE, and a Click CLI. It is
designed for a few agents and second-level delivery, not high-throughput
messaging or workflow orchestration.

## Core Guarantees

- Events are persisted before delivery.
- Delivery is at least once; pending or delivered events replay after
  reconnect until they are ACKed or moved to the failed state.
- `agent-bus listen` acknowledges an event only after its matching handler
  exits successfully.
- Handler failures are counted by the server across listener processes;
  terminal failures remain inspectable until the recipient explicitly requeues
  them.
- Per-agent tokens scope sending, receiving, inspection, and ACK operations to
  one agent identity.
- Event payloads and local handlers remain runtime-agnostic.

At-least-once delivery means a handler may see the same event more than once.
Make handlers idempotent and use the event ID or a stable `payload.task_id` for
deduplication.

## Quick Start

This walkthrough verifies Agent Bus Core with an `echo` handler. It does not
require OpenCode or another AI runtime.

### 1. Deploy the Server

Clone Agent Bus on the server:

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
```

Then choose one deployment method:

| Method | Requirements | Install |
| --- | --- | --- |
| Docker Compose | Docker Engine with Compose v2 | `bash scripts/install-docker.sh` |
| Native systemd | Linux with systemd and Python 3.11+ | `bash scripts/install.sh` |

Both installers generate separate `architect` and `coder` tokens, start the
server, verify its health, and print new tokens only on first installation.
Save each token through a trusted channel; the names are installer defaults,
not hardcoded protocol roles.

Docker runs as a non-root user and stores SQLite in the `agent-bus-data` named
volume. The systemd path stores SQLite under `/opt/agent-bus/data`. Both serve
on port 8800; Docker publishes it only on localhost by default. Use Tailscale or
another trusted private transport for remote access.

For logs, backup and restore, upgrades, rollback, custom identities, and manual
installation, see the
[installation and security guide](docs/guide/installation.md).

### 2. Configure Two Clients

Install the CLI on the sender and receiver, store each printed token in its own
protected credential file, and create the `architect` and `coder` contexts.
The [client setup guide](docs/guide/installation.md#native-client-contexts)
contains the macOS, Linux, and Windows commands.

Run `agent-bus doctor` on both clients before continuing.

### 3. Verify the Event Loop

Start an `echo` listener on the receiver:

```bash
agent-bus --context coder listen --on task:new "echo {payload.prompt}"
```

Send one event from the sender:

```bash
agent-bus --context architect send \
  --to coder \
  --type task:new \
  --payload '{"task_id":"quickstart-001","prompt":"Hello from Agent Bus"}'
```

The receiver should print the event, echo the prompt, and ACK it. Stop the
listener with Ctrl+C, then confirm its durable inbox is empty:

```bash
agent-bus --context coder pending
```

An empty JSON array (`[]`) proves the `send → receive → handler → ACK` path.
Production adapters still need their own workspace, idempotency, and local tool
policies; those concerns remain outside Agent Bus Core.

## Production Deployment

For a remote deployment, prefer Tailscale, HTTPS, a tunnel, or another trusted
private transport. Do not expose bearer-token HTTP on `8800/tcp` directly to
the public internet. A failed request to the VPS public IP is not a deployment
failure when the Tailscale URL and the event round trip work.

The optional bootstrap token endpoint is disabled by default. Its secret can
request any configured agent token, so treat it as a high-sensitivity
provisioning credential. Firewall setup, bootstrap provisioning, POSIX atomic
writes, Windows ACLs, and legacy `listener.env` compatibility are documented in
the [installation and security guide](docs/guide/installation.md).

## Connecting a Local AI Runtime

A local runtime normally performs this sequence:

```text
receive task:new
→ prepare workspace
→ invoke local tool
→ report result
```

For example, after OpenCode is installed and configured on the receiver, a
demonstration listener can invoke it with:

```bash
agent-bus listen --on task:new "opencode run {payload.prompt}"
```

The handler command is local configuration. Agent Bus does not clone or select
repositories, construct prompts, run tests, commit changes, push branches, or
open pull requests. A single `listen --on` command is useful for demonstrations;
a durable Worker Runtime needs its own workspace policy, idempotency, result
events, and failure handling. Start with [`docs/worker.md`](docs/worker.md) and
adapt the reference files under [`examples/`](examples/).

## Common CLI Commands

```bash
agent-bus doctor
agent-bus doctor --send-test
agent-bus send --to coder --type task:new --payload-file payload.json
agent-bus pending
agent-bus failed
agent-bus requeue 42
agent-bus ack 42
agent-bus listen --on task:new "echo {payload.prompt}"
agent-bus context list
agent-bus context show
```

- `doctor` checks configuration, server health, and the current token's agent
  scope. `--send-test` additionally creates and ACKs a real self-addressed
  event; the event record remains persisted.
- `pending` lists events in the pending or delivered state for the selected
  agent.
- `failed` lists terminal failed events, including the cumulative attempt count
  and last error. `requeue EVENT_ID` explicitly returns one of those events to
  pending without discarding its failure evidence.
- `ack EVENT_ID` manually acknowledges an event addressed to the selected
  agent.
- `context list` and `context show` display connection and credential
  references, never token values.

Run `agent-bus COMMAND --help` for the complete options. Explicit flags and the
`AGENT_BUS_URL`, `AGENT_BUS_TOKEN`, and `AGENT_BUS_AGENT` environment variables
remain available for CI and compatibility use.

## Documentation

| Document | Use it for |
| --- | --- |
| [Installation and security](docs/guide/installation.md) | systemd and Docker server deployment, persistence, networking, token provisioning, bootstrap, Windows ACLs, and compatibility setup |
| [Worker Runtime](docs/worker.md) | Designing the adapter that invokes local tools and reports results |
| [Product positioning](docs/product-positioning.md) | Understanding the boundary between the relay, adapters, and workflow systems |
| [Recommended practices](docs/recommended-practices.md) | Operating the current lightweight deployment and deciding when to add infrastructure |
| [Protocol](docs/protocol.md) | Event fields, delivery semantics, event conventions, and API endpoints |
| [Roadmap](docs/roadmap.md) | Current limitations and staged future work |
| [Design](docs/design.md) | Architecture, SQLite/SSE choices, and the security model |
| [Changelog](CHANGELOG.md) | Released capabilities, changes, and explicit boundaries |

## Development

Agent Bus requires Python 3.11+. The repository test script requires
[`uv`](https://docs.astral.sh/uv/), and the lint command requires Ruff.

```bash
ruff check client server tests
python -m compileall -q client server tests
bash scripts/test.sh
```

`scripts/test.sh` runs the unit suite, starts a local server, and exercises the
event API and CLI integration path.
