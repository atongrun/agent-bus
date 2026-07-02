# Agent Bus — Client Installation Guide

> For AI agents: follow this guide step by step to install and configure the agent-bus client.

## Prerequisites

- Python 3.10+
- pip or uv

## 1. Install the client

```bash
# Clone the repo
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus

# Install with pip
pip install -e .
```

Verify:
```bash
agent-bus --help
```

## 2. Configure

Set these environment variables:

```bash
# VPS server URL (ask your human for this)
export AGENT_BUS_URL=http://124.222.104.232:8800

# Shared authentication token (ask your human for this)
export AGENT_BUS_TOKEN=your-secret-token

# Your agent identity: "architect" or "coder"
export AGENT_BUS_AGENT=coder
```

Make them permanent (add to `~/.bashrc` or `~/.zshrc`).

## 3. Test connectivity

```bash
# Health check
curl $AGENT_BUS_URL/health

# Should return: {"status":"ok"}
```

## 4. Start listening

```bash
agent-bus listen
```

This connects to the VPS via SSE and prints incoming events. Keep it running in a terminal.

## 5. Send an event

```bash
agent-bus send --to coder --type task:new \
  --payload '{"url":"https://github.com/xxx/issues/1","task_id":"issue-1"}'
```

## Your Role

| Agent | Machine | What to do |
|-------|---------|------------|
| `architect` | Mac | Plan tasks → send `task:new`. When you get `pr:ready` → review the PR. |
| `coder` | Windows | Listen for `task:new`. Implement → submit PR → send `pr:ready`. |

## Troubleshooting

- **`agent-bus: command not found`**: pip install didn't add to PATH. Use `python -m agent_bus_client.cli` instead.
- **Connection refused**: Check AGENT_BUS_URL and that the VPS server is running.
- **401 Unauthorized**: Check AGENT_BUS_TOKEN matches the server's `.env`.

## Need the server?

If the server isn't running yet, tell your human to deploy it on the VPS:
```bash
ssh your-vps
cd /opt/agent-bus
bash scripts/install.sh
systemctl start agent-bus
```
