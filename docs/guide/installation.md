# Agent Bus Installation Guide

This guide covers the v0.2 lightweight deployment path: one server process and
foreground CLI listeners on each agent machine.

## Server

On a Linux VPS or local Linux machine:

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
bash scripts/install.sh
```

The installer creates `/etc/agent-bus/.env` with per-agent tokens:

```text
AGENT_BUS_AGENT_TOKENS=architect=<architect-token>,coder=<coder-token>
AGENT_BUS_HOST=0.0.0.0
AGENT_BUS_PORT=8800
AGENT_BUS_DB_PATH=/opt/agent-bus/data/agent-bus.db
```

Check the service:

```bash
sudo systemctl status agent-bus
curl http://localhost:8800/health
```

## Mac Codex Client

```bash
pip install agent-bus

export AGENT_BUS_URL=http://your-vps:8800
export AGENT_BUS_TOKEN=<architect-token>
export AGENT_BUS_AGENT=architect

agent-bus send --to coder --type task:new --payload-file payload.json
agent-bus listen --agent architect --on pr:ready "echo PR ready: {payload.pr_url}"
```

## Windows Open Code Client

Start with a foreground listener so failures are visible.

PowerShell:

```powershell
pip install agent-bus

$env:AGENT_BUS_URL = "http://your-vps:8800"
$env:AGENT_BUS_TOKEN = "<coder-token>"
$env:AGENT_BUS_AGENT = "coder"

agent-bus listen --agent coder --on task:new "opencode run --prompt {payload.prompt}"
```

The event is ACKed only if the command exits with code `0`.

## Local Multi-Agent Mode

For local agents, point all clients at localhost:

```bash
export AGENT_BUS_URL=http://localhost:8800
export AGENT_BUS_AGENT=verifier
export AGENT_BUS_TOKEN=<verifier-token>
agent-bus listen --agent verifier --on task:new "python verify.py {payload.task_id}"
```

## Troubleshooting

- Connection refused: check `AGENT_BUS_URL` and `systemctl status agent-bus`.
- `401 Unauthorized`: token is missing or wrong.
- `403 Forbidden`: token belongs to a different agent.
- Event repeats: the handler did not ACK, usually because it failed or timed out.
- Complex JSON quoting fails: use `agent-bus send --payload-file payload.json`.
