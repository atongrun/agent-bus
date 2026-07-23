# Agent Bus Installation Guide

This guide covers the v0.2 lightweight deployment paths: one server process
installed through systemd or Docker Compose, plus foreground CLI listeners or
external adapters on each agent machine.

For the rationale behind this lightweight path, see
[../recommended-practices.md](../recommended-practices.md).

## Server

Choose either the native systemd installer or Docker Compose. Both run the same
single-process Agent Bus Core and use the same `AGENT_BUS_*` configuration. The
Docker path is an alternative deployment method, not a migration requirement.

### Native systemd Server

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

### Docker Compose Server

The Docker deployment needs Docker Engine with the Compose v2 plugin. It builds
the server from the checked-out release, runs it as a non-root user, stores the
SQLite database in the `agent-bus-data` named volume, and publishes port 8800
only on localhost by default.

Clone a release checkout, then create a protected runtime environment file
outside the repository. Generate each token independently and replace the
placeholders without printing real values into shell history or logs:

```bash
git clone https://github.com/atongrun/agent-bus.git
cd agent-bus

install -d -m 700 ~/.config/agent-bus
install -m 600 /dev/null ~/.config/agent-bus/server.docker.env
${EDITOR:-vi} ~/.config/agent-bus/server.docker.env
```

The file must contain the per-agent token mapping. Bootstrap remains disabled
unless its secret is explicitly added:

```text
AGENT_BUS_AGENT_TOKENS=sender=<sender-token>,receiver=<receiver-token>
# AGENT_BUS_BOOTSTRAP_SECRET=<random-bootstrap-secret>
```

Do not copy this file into the checkout, pass secrets as Docker build arguments,
or commit it. Compose fails before starting when `AGENT_BUS_AGENT_TOKENS` is
missing. Start the service and verify its health:

```bash
docker compose --env-file ~/.config/agent-bus/server.docker.env up -d --build
docker compose --env-file ~/.config/agent-bus/server.docker.env ps
docker compose --env-file ~/.config/agent-bus/server.docker.env logs --tail 50 agent-bus
curl http://127.0.0.1:8800/health
```

The health response must contain `"status":"ok"`. Normal operations are:

```bash
docker compose --env-file ~/.config/agent-bus/server.docker.env logs -f agent-bus
docker compose --env-file ~/.config/agent-bus/server.docker.env stop
docker compose --env-file ~/.config/agent-bus/server.docker.env start
docker compose --env-file ~/.config/agent-bus/server.docker.env down
```

`docker compose down` removes the container and network but preserves the named
volume. Do not use `docker compose down -v` unless you intentionally want to
delete the durable event database.

#### Docker Data Backup And Restore

Take a cold backup before every upgrade. Stopping the service first ensures the
SQLite database and its WAL files form one consistent snapshot:

```bash
mkdir -m 700 agent-bus-backup
docker compose --env-file ~/.config/agent-bus/server.docker.env stop agent-bus
docker run --rm \
  -v agent-bus-data:/data:ro \
  -v "$PWD/agent-bus-backup:/backup" \
  alpine:3.20 \
  tar -C /data -czf /backup/agent-bus-data.tgz .
docker compose --env-file ~/.config/agent-bus/server.docker.env start agent-bus
```

Keep `~/.config/agent-bus/server.docker.env` in the same protected backup system, but never
put it inside the database archive or repository. To restore, first preserve the
current volume separately, stop the service, and then replace the volume
contents from a trusted backup:

```bash
docker compose --env-file ~/.config/agent-bus/server.docker.env stop agent-bus
docker run --rm \
  -v agent-bus-data:/data \
  alpine:3.20 \
  sh -c 'find /data -mindepth 1 -delete'
docker run --rm \
  -v agent-bus-data:/data \
  -v "$PWD/agent-bus-backup:/backup:ro" \
  alpine:3.20 \
  tar -C /data -xzf /backup/agent-bus-data.tgz
docker compose --env-file ~/.config/agent-bus/server.docker.env start agent-bus
curl http://127.0.0.1:8800/health
```

#### Docker Upgrade And Rollback

Back up both the named volume and protected environment file before changing
versions. Build from an explicit release tag so rollback remains auditable:

```bash
git fetch --tags
git checkout <new-release-tag>
docker compose --env-file ~/.config/agent-bus/server.docker.env build --pull
docker compose --env-file ~/.config/agent-bus/server.docker.env up -d
curl http://127.0.0.1:8800/health
```

Then complete the event loop below before declaring the upgrade ready. To roll
back the application, check out the previous release tag and rebuild. If the
failed upgrade changed durable data incompatibly, stop the service and restore
the pre-upgrade volume snapshot before starting the previous image. Never infer
database compatibility from a successful container start alone.

#### Docker Deployment Acceptance

Configure sender and receiver client contexts against this server, then prove
the durable path rather than relying on container status alone:

1. Run `agent-bus doctor` from both clients.
2. Send a unique event with the sender token.
3. Query `pending` with the recipient token and record the event ID.
4. Recreate the container with `docker compose --env-file
   ~/.config/agent-bus/server.docker.env up -d --force-recreate`, query `pending` again, and
   confirm the same event ID survived in the named volume.
5. ACK that ID with the recipient token.
6. Query `pending` again and confirm it is empty.

The container includes only Agent Bus Core. Local Worker Runtime processes,
listener supervision, Tailscale, TLS termination, and reverse proxies remain
outside it.

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

The Compose deployment binds to `127.0.0.1` by default. To publish directly on
the VPS Tailscale address, add the following non-secret value to the protected
Docker environment file and recreate the service:

```text
AGENT_BUS_BIND_ADDRESS=<vps-tailscale-ip>
```

```bash
docker compose --env-file ~/.config/agent-bus/server.docker.env up -d
curl http://<vps-tailscale-ip>:8800/health
```

Do not set `AGENT_BUS_BIND_ADDRESS=0.0.0.0` unless an independently verified
firewall or private network boundary prevents public access.

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

Install the CLI, obtain the matching agent token, then create a named context.
Contexts contain only a server URL, an agent identity, and a credential
reference.

### Obtaining a Client Token

The server installer generates per-agent tokens. There are two supported
provisioning paths:

1. Copy the matching token shown during the first install through an existing
   trusted channel into an owner-only credentials file.
2. Optionally enable `POST /bootstrap/token` and exchange a separately
   provisioned bootstrap secret for one agent token.

The bootstrap endpoint is disabled by default. To enable it, add a strong
random value to the server's protected `/etc/agent-bus/.env` and restart the
service:

```text
AGENT_BUS_BOOTSTRAP_SECRET=<random-bootstrap-secret>
```

```bash
sudo chmod 600 /etc/agent-bus/.env
sudo systemctl restart agent-bus
```

Provision that bootstrap secret to the client through an existing secure
channel. Do not pass it with curl `-H` or `--header`, because command-line
arguments can be visible to other local processes. On POSIX, keep the header in
a private curl config instead:

```bash
mkdir -p ~/.config/agent-bus
chmod 700 ~/.config/agent-bus
install -m 600 /dev/null ~/.config/agent-bus/bootstrap.curl
```

Edit `bootstrap.curl` to contain exactly one header line:

```text
header = "X-Bootstrap-Secret: <bootstrap-secret>"
```

Exchange it for the selected agent token without writing either secret to the
terminal. Write to a private temporary file and replace the destination only
after curl and JSON parsing both succeed, so a failed exchange cannot erase a
working credential:

```bash
set -o pipefail
umask 077
credential_file="$HOME/.config/agent-bus/sender.credentials.env"
temporary_file="$(mktemp "$HOME/.config/agent-bus/.sender.credentials.env.XXXXXX")"
if curl -fsS -K ~/.config/agent-bus/bootstrap.curl \
    -H 'Content-Type: application/json' \
    --data '{"agent":"sender"}' \
    http://<vps-tailscale-ip>:8800/bootstrap/token |
  python3 -c 'import json, sys; print("AGENT_BUS_SENDER_TOKEN=" + json.load(sys.stdin)["token"])' \
    > "$temporary_file"
then
  chmod 600 "$temporary_file"
  mv -f "$temporary_file" "$credential_file"
else
  rm -f "$temporary_file"
  exit 1
fi
```

On Windows PowerShell, protect the configuration directory with a
current-user-only NTFS ACL before creating either file. Store the bootstrap
secret as the only line in `bootstrap.secret`; reading it into a PowerShell
variable keeps it out of process arguments:

```powershell
$root = Join-Path $env:APPDATA "agent-bus"
New-Item -ItemType Directory -Force -Path $root | Out-Null
icacls $root /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to protect Agent Bus config directory" }
$bootstrapPath = Join-Path $root "bootstrap.secret"
New-Item -ItemType File -Force -Path $bootstrapPath | Out-Null
notepad $bootstrapPath

$secret = (Get-Content -Raw $bootstrapPath).Trim()
$response = Invoke-RestMethod -Method Post `
  -Uri "http://<vps-tailscale-ip>:8800/bootstrap/token" `
  -Headers @{"X-Bootstrap-Secret" = $secret} `
  -ContentType "application/json" `
  -Body '{"agent":"receiver"}'
$temporaryFile = Join-Path $root ".receiver.credentials.env.tmp"
$credentialFile = Join-Path $root "receiver.credentials.env"
Set-Content -Path $temporaryFile `
  -Value "AGENT_BUS_RECEIVER_TOKEN=$($response.token)" -Encoding ascii
icacls $temporaryFile /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
if ($LASTEXITCODE -ne 0) {
  Remove-Item -Force $temporaryFile
  throw "Failed to protect Agent Bus credential file"
}
Move-Item -Force $temporaryFile $credentialFile
```

Expected failures deliberately reveal little: disabled endpoint or unknown
agent returns `404`; a missing or incorrect bootstrap secret returns `401`.
The current bootstrap secret is not role-scoped—it can request any configured
agent token—so protect it like a high-sensitivity provisioning credential and
use the endpoint only over Tailscale, HTTPS, or another trusted private
transport. Leaving it unset is recommended when tokens are provisioned by
another secure mechanism.

### Creating the Context

Whether provisioned manually or through the bootstrap endpoint, keep the token
in an owner-only credential file outside any repository, for example
`~/.config/agent-bus/sender.credentials.env`, containing
`AGENT_BUS_SENDER_TOKEN=<agent-specific-token>`. Use mode `0600` on POSIX or a
current-user-only ACL on Windows. Then reference it without copying the value:

```bash
pip install agent-bus

agent-bus context add sender \
  --server http://<vps-tailscale-ip>:8800 \
  --agent sender \
  --token-env AGENT_BUS_SENDER_TOKEN \
  --env-file ~/.config/agent-bus/sender.credentials.env \
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
  --env-file ~/.config/agent-bus/receiver.credentials.env \
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
