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

The current systemd server installer creates two agent identities named `architect`
and `coder`. In this walkthrough, `architect` is the sender and `coder` is the
receiver. These names are installer defaults, not hardcoded protocol roles.

### 1. Install the Server

Choose one server deployment path. Both run the same Agent Bus Core API on
port 8800; do not install both on the same host.

#### Option A: Native systemd

Run this on a fresh systemd-based Linux server whose `python3` is version 3.11
or newer:

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
python3 --version
bash scripts/install.sh
```

The installer:

- copies the checkout to `/opt/agent-bus/app`;
- creates a virtual environment and installs the project into it;
- creates `/etc/agent-bus/.env` and `/opt/agent-bus/data`;
- installs and starts `agent-bus.service`;
- prints newly generated `architect` and `coder` tokens on the first install.

Save each printed token through a trusted channel. The server also stores the
token mapping in the root-only `/etc/agent-bus/.env`; subsequent installer
runs do not print existing tokens.

Verify the service on the Linux server:

```bash
sudo systemctl status agent-bus
curl http://127.0.0.1:8800/health
```

The health response must contain `"status":"ok"`.

#### Option B: Docker Compose

Use this path on a Linux server with Docker Engine and the Compose v2 plugin.
It runs the server as a non-root user, keeps SQLite in a persistent named
volume, and publishes port 8800 only on localhost by default:

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
install -d -m 700 ~/.config/agent-bus
install -m 600 /dev/null ~/.config/agent-bus/server.docker.env
${EDITOR:-vi} ~/.config/agent-bus/server.docker.env
# Add: AGENT_BUS_AGENT_TOKENS=architect=<token>,coder=<token>
docker compose --env-file ~/.config/agent-bus/server.docker.env up -d --build
curl http://127.0.0.1:8800/health
```

Do not commit `server.docker.env`. For Tailscale binding, backup/restore, upgrades, and
the full deployment verification loop, follow the
[Docker server instructions](docs/guide/installation.md#docker-compose-server).
The existing systemd installer remains supported.

### 2. Install the CLI on Each Client

The package is not currently published on PyPI. On each client with Git and
Python 3.11+, install it from a source checkout.

On macOS or Linux:

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
agent-bus --help
```

On Windows PowerShell:

```powershell
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
agent-bus --help
```

The remaining Quick Start commands use POSIX paths. Windows clients support the
same context and event commands; follow the
[Windows credential-file instructions](docs/guide/installation.md#obtaining-a-client-token)
to apply a current-user-only ACL instead of POSIX file modes.

### 3. Configure the Sender

Run this on the sender machine. Put only the `architect` token in an owner-only
file outside any repository:

```bash
mkdir -p ~/.config/agent-bus
chmod 700 ~/.config/agent-bus
install -m 600 /dev/null ~/.config/agent-bus/architect.credentials.env
```

Edit that file so it contains one line:

```text
AGENT_BUS_ARCHITECT_TOKEN=<architect-token>
```

Create and select the sender context:

```bash
agent-bus context add architect \
  --server http://<vps-tailscale-ip>:8800 \
  --agent architect \
  --token-env AGENT_BUS_ARCHITECT_TOKEN \
  --env-file ~/.config/agent-bus/architect.credentials.env \
  --select

agent-bus doctor
```

`doctor` checks that configuration is present, `/health` is reachable, and the
token can list pending events for `architect`. It does not validate a local AI
runtime or workspace.

### 4. Configure and Start the Receiver

Run this on the receiver machine using the separately provisioned `coder`
token:

```bash
mkdir -p ~/.config/agent-bus
chmod 700 ~/.config/agent-bus
install -m 600 /dev/null ~/.config/agent-bus/coder.credentials.env
```

Edit that file so it contains one line:

```text
AGENT_BUS_CODER_TOKEN=<coder-token>
```

Create the receiver context and start a listener:

```bash
agent-bus context add coder \
  --server http://<vps-tailscale-ip>:8800 \
  --agent coder \
  --token-env AGENT_BUS_CODER_TOKEN \
  --env-file ~/.config/agent-bus/coder.credentials.env \
  --select

agent-bus doctor
agent-bus listen --on task:new "echo {payload.prompt}"
```

Leave the listener running while you send the test event.

### 5. Send One Test Event

Back on the sender machine, create the payload explicitly:

```bash
cat > payload.json <<'JSON'
{
  "task_id": "quickstart-001",
  "prompt": "Hello from Agent Bus"
}
JSON

agent-bus --context architect send \
  --to coder \
  --type task:new \
  --payload-file payload.json
```

The sender should print `Event sent` with a server-assigned event ID. The
receiver should print the event, run `echo`, report handler exit code `0`, and
print `ACKed`.

After the listener has handled the event, stop it with Ctrl+C and verify on the
receiver machine:

```bash
agent-bus --context coder pending
```

The result should be an empty JSON array (`[]`). At this point Agent Bus Core is
installed and the durable send, receive, handler, and ACK path works. A complete
AI Worker workflow still requires a local adapter that manages the workspace
and invokes the chosen tool.

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
