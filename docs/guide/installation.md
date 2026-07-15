# Agent Bus Installation Guide

This guide covers the v0.2 lightweight deployment path: one server process and
foreground CLI listeners or external adapters on each agent machine.

For the rationale behind this lightweight path, see
[../recommended-practices.md](../recommended-practices.md).

## Server

On a Linux VPS or local Linux machine:

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus
bash scripts/install.sh
```

The installer creates `/etc/agent-bus/.env` with per-agent tokens:

```text
AGENT_BUS_AGENT_TOKENS=sender=<sender-token>,receiver=<receiver-token>
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

From a non-tailnet path, `http://<vps-public-ip>:8800/health` should fail. Do
not treat public-IP `8800/tcp` failure as a deployment failure when the
Tailscale URL works.

Use the Tailscale URL as the `--server` value when creating client contexts.

One concrete production path can look like this:

```text
Mac client -> VPS Agent Bus over Tailscale -> Windows receiver
```

This is an example topology, not a built-in Agent Bus role model. The endpoint
tools can be Codex, OpenCode, Claude Code, shell scripts, test runners, or any
other local runtime.

Complete one event loop before declaring the deployment ready:

1. Send a test event with the sender agent token.
2. Query `pending` with the recipient agent token.
3. ACK the event with the recipient agent token.
4. Query `pending` again and confirm it is empty.

## Native Client Contexts

Install the CLI, then create a named context. Contexts contain only a server
URL, an agent identity, and a credential reference:

First create an owner-only credential file outside any repository, for example
`~/.config/agent-bus/credentials.env`, containing
`AGENT_BUS_SENDER_TOKEN=<agent-specific-token>`. Use mode `0600` on POSIX or a
current-user-only ACL on Windows. Then reference it without copying the value:

```bash
pip install agent-bus

agent-bus context add sender \
  --server http://<vps-tailscale-ip>:8800 \
  --agent sender \
  --token-env AGENT_BUS_SENDER_TOKEN \
  --env-file ~/.config/agent-bus/credentials.env \
  --select

agent-bus doctor
agent-bus send --to receiver --type task:new --payload-file payload.json
```

For a receiver, add a separate identity and select it on that machine:

```bash
agent-bus context add receiver \
  --server http://<vps-tailscale-ip>:8800 \
  --agent receiver \
  --token-env AGENT_BUS_RECEIVER_TOKEN \
  --env-file ~/.config/agent-bus/credentials.env \
  --select

agent-bus doctor
agent-bus listen --on task:new "opencode run --prompt {payload.prompt}"
```

The handler is a local runtime choice, not context data. Git, AI execution,
workspace setup, and PR creation belong to the adapter outside Agent Bus core.
The event is ACKed only if the handler exits with code `0`.

Contexts are stored as program-generated JSON under:

- POSIX: `$XDG_CONFIG_HOME/agent-bus`, otherwise `~/.config/agent-bus`
- Windows: `%APPDATA%\agent-bus`; if `APPDATA` is unavailable, Agent Bus warns
  and uses `%USERPROFILE%\AppData\Roaming\agent-bus`

The selected name is stored in `current-context`; named files live under
`contexts/<validated-name>.json`. Both are written atomically and made private.
Names cannot contain path separators or traversal components.

Credential references support:

- `--token-env NAME`: read `NAME` from the process environment.
- `--token-env KEY --env-file PATH`: read only `KEY` from the explicit file.

`PATH` must be absolute or start with `~`, so the credential source cannot
silently change when a command runs from a different working directory.

Token values are never written to context JSON and are never printed by
`context list`, `context show`, or `doctor`. Repository-local `.env` files are
not auto-discovered.

Runtime precedence is `CLI flags > AGENT_BUS_* environment variables > selected
context > defaults`. This preserves existing scripts and lets CI remain
context-free:

```bash
export AGENT_BUS_URL=http://<vps-tailscale-ip>:8800
export AGENT_BUS_TOKEN=<sender-token>
export AGENT_BUS_AGENT=sender
agent-bus send --to receiver --type task:new --payload-file payload.json
```

Use `agent-bus context list`, `show`, `use`, and `delete` to manage contexts.
Use `agent-bus --context NAME pending` for a one-command selection override.

## Receiver Adapter

The receiver listens for events and invokes a local runtime. Agent Bus only
delivers the event and tracks ACK state; Git, AI execution, workspace setup,
and PR creation belong to the adapter.

### Optional Windows Polling Adapter

If the Windows machine does not yet have Python 3.11 or the `agent-bus` CLI,
use the example polling adapter to prove the private-network event loop first:

```powershell
$env:AGENT_BUS_URL = "http://<vps-tailscale-ip>:8800"
$env:AGENT_BUS_TOKEN = "<receiver-token>"
$env:AGENT_BUS_AGENT = "receiver"

.\examples\windows\poll-listener.ps1 `
  -Command opencode `
  -CommandArgs @("run", "--prompt")
```

This adapter polls `pending`, invokes the configured command with
`payload.prompt` as a data argument, and ACKs only when the handler exits with
code `0`. It is a bootstrap example outside Agent Bus core. The normal CLI
listener remains the preferred long-running path once Python 3.11+ and the
`agent-bus` package are installed.

A second variant, `scripts/windows-poll-listener.ps1`, takes the handler as an
`-OnTaskNew` template and additionally supports `-Workdir`:

```powershell
$env:AGENT_BUS_URL = "http://<vps-tailscale-ip>:8800"
$env:AGENT_BUS_TOKEN = "<coder-token>"
$env:AGENT_BUS_AGENT = "coder"

powershell -ExecutionPolicy Bypass -File .\scripts\windows-poll-listener.ps1 `
  -OnTaskNew 'opencode run --prompt {payload.prompt}'
```

To run the handler inside a specific project directory (mirroring the main
CLI's `--workdir`), pass `-Workdir`. The path must exist and be a directory,
otherwise the listener errors out before polling starts; the original directory
is restored after each handler run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows-poll-listener.ps1 `
  -Workdir "D:\path\to\your-project" `
  -OnTaskNew 'opencode run --prompt {payload.prompt}'
```

`-Workdir` is a local static config: the path is never taken from a remote
payload. If `payload.repo` / `payload.workdir` routing is added later, it must
be resolved through a local whitelist map, never by trusting a remote absolute
path directly.

Minimal verification (no server needed): point the listener at a throwaway
directory and a no-op handler, confirm the banner prints the resolved workdir
and the handler runs there:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows-poll-listener.ps1 `
  -Url http://localhost:8800 -Token dummy -Once `
  -Workdir "D:\path\to\your-project" `
  -OnTaskNew 'cd'
```

`-Workdir` pointing at a missing or non-directory path must abort before any
polling with `Workdir does not exist` / `Workdir is not a directory`.

## Local Multi-Agent Mode

For local agents, use a localhost context:

```bash
agent-bus context add verifier \
  --server http://localhost:8800 \
  --agent verifier \
  --token-env AGENT_BUS_VERIFIER_TOKEN \
  --select
agent-bus listen --on task:new "python verify.py {payload.task_id}"
```

## Legacy listener.env Compatibility

Existing Agent Workflow/OpenCode listeners may continue to use `agent-bus init`
and source the generated `listener.env` before `agent-bus doctor --listener`.
That compatibility entry point still records workflow-specific repo/script
paths and network warm-up settings in the legacy shell environment; those
fields are intentionally not accepted in native contexts. Migrate normal CLI
connection settings to `agent-bus context add` when convenient; no immediate
cutover is required.

## Troubleshooting

- Connection refused: check `AGENT_BUS_URL` and `systemctl status agent-bus`.
- `curl` works but the agent command fails: rerun the check from the real local
  environment. Sandboxed agent networking can produce false negatives for
  private network URLs.
- `agent-bus` command not found: use the project virtual environment or install
  the CLI into the active Python environment. A configured local wrapper script
  is preferred for repeated use.
- Tailnet works but public access fails: expected for Tailscale-only
  deployments.
- Public access works unexpectedly: remove firewall or cloud security-group
  rules that expose `8800/tcp`.
- `401 Unauthorized`: token is missing or wrong.
- `403 Forbidden`: token belongs to a different agent.
- Event repeats: the handler did not ACK, usually because it failed or timed out.
- Complex JSON quoting fails: use `agent-bus send --payload-file payload.json`.
- Python version errors: install Python 3.11+ on the server. Do not relax the
  project version requirement without testing the full suite on the lower
  Python version.
