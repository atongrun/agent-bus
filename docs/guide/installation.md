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

### Recommended VPS Network Boundary: Tailscale

For a VPS shared by your own machines, prefer Tailscale-only access instead of
exposing `8800/tcp` to the public internet. Agent Bus can keep listening on
`0.0.0.0`; the firewall should limit inbound access to the Tailscale interface.

Check Tailscale and find the VPS tailnet address:

```bash
tailscale status
tailscale ip -4
```

If `ufw` is enabled, allow Agent Bus only on `tailscale0`:

```bash
sudo ufw allow in on tailscale0 to any port 8800 proto tcp
```

If a previous rule exposed `8800/tcp` publicly, remove that public rule after
the Tailscale rule is in place:

```bash
sudo ufw delete allow 8800/tcp
```

Also remove any cloud-provider security-group rule that exposes public
`8800/tcp`. Keep SSH and any existing remote-access services untouched.

Verify both local and tailnet access:

```bash
curl http://127.0.0.1:8800/health
curl http://<vps-tailscale-ip>:8800/health
```

From a non-tailnet path, `http://<vps-public-ip>:8800/health` should fail.

Use the Tailscale URL on clients:

```bash
export AGENT_BUS_URL=http://<vps-tailscale-ip>:8800
```

Complete one event loop before declaring the deployment ready:

1. Send a test event with the sender agent token.
2. Query `pending` with the recipient agent token.
3. ACK the event with the recipient agent token.
4. Query `pending` again and confirm it is empty.

## Mac Codex Client

```bash
pip install agent-bus

export AGENT_BUS_URL=http://<vps-tailscale-ip>:8800
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

$env:AGENT_BUS_URL = "http://<vps-tailscale-ip>:8800"
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
- Tailnet works but public access fails: this is expected for Tailscale-only
  deployments.
- `401 Unauthorized`: token is missing or wrong.
- `403 Forbidden`: token belongs to a different agent.
- Event repeats: the handler did not ACK, usually because it failed or timed out.
- Complex JSON quoting fails: use `agent-bus send --payload-file payload.json`.
- Python version errors: install Python 3.11+ on the server. Do not relax the
  project version requirement without testing the full suite on the lower
  Python version.
