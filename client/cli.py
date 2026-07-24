"""Agent Bus CLI — send and listen for agent events."""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
import httpx

from client.context_config import (
    ContextError,
    ContextStore,
    RuntimeConfig,
    default_context_root,
    protect_credential_file,
    resolve_runtime_config,
    validate_context_configuration,
    write_credential_file,
)

from client.listener_config import (
    default_config_path,
    listener_environment_issues,
    render_listener_env,
    shell_quote,
    source_path,
    warm_network_path,
    write_listener_env,
)


def get_config():
    """Get configuration from environment variables."""
    url = os.environ.get("AGENT_BUS_URL", "http://localhost:8800")
    token = os.environ.get("AGENT_BUS_TOKEN", "")
    agent = os.environ.get("AGENT_BUS_AGENT", "")
    return url.rstrip("/"), token, agent


def get_headers(token: str) -> dict:
    """Get HTTP headers with auth."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _load_payload(payload: str, payload_file: str | None) -> dict:
    """Load a JSON payload from an inline string or file."""
    if payload_file:
        try:
            payload = Path(payload_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Could not read --payload-file: {exc}") from exc
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Payload must be valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise click.ClickException("Payload must be a JSON object")
    return loaded


def _post_ack(
    base_url: str,
    token: str,
    event_id: int,
    expected_retry_count: int | None = None,
) -> bool:
    """ACK an event and print a short diagnostic."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{base_url}/events/{event_id}/ack",
                headers=get_headers(token),
                params=(
                    {"expected_retry_count": expected_retry_count}
                    if expected_retry_count is not None
                    else None
                ),
            )
    except Exception as exc:
        click.echo(f"  ACK error: {exc}", err=True)
        return False

    if resp.status_code == 200:
        click.echo("  ACKed")
        return True

    click.echo(f"  ACK failed: {resp.status_code} {resp.text}", err=True)
    return False


def _post_fail(
    base_url: str,
    token: str,
    event_id: int,
    error: str,
    *,
    expected_retry_count: int,
    max_attempts: int,
) -> dict | None:
    """Persist one failed attempt and return the server-authoritative state.

    Never raises out of the listen loop: on network error it prints and
    returns None, mirroring _post_ack.
    """
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{base_url}/events/{event_id}/fail",
                headers=get_headers(token),
                json={
                    "error": error,
                    "expected_retry_count": expected_retry_count,
                    "max_attempts": max_attempts,
                },
            )
    except Exception as exc:
        click.echo(f"  FAIL error: {exc}", err=True)
        return None

    if resp.status_code == 200:
        state = resp.json()
        click.echo(
            "  Failure recorded: "
            f"attempts={state['retry_count']} status={state['status']}"
        )
        return state

    click.echo(f"  FAIL failed: {resp.status_code} {resp.text}", err=True)
    return None


_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def _lookup_template_value(event_data: dict, expression: str):
    """Resolve placeholders such as payload.task_id against an event object."""
    current = event_data
    for part in expression.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(expression)
    if isinstance(current, (dict, list)):
        return json.dumps(current, ensure_ascii=False)
    return str(current)


def render_command(template: str, event_data: dict) -> list[str]:
    """Render a handler command template for one event into an argv list.

    The template is split into tokens ONCE with ``shlex.split`` (POSIX rules: honours
    double/single quotes, so a quoted path with spaces stays one token). Any token that
    is exactly a ``{placeholder}`` is replaced by the raw looked-up value as a single
    argv element — no shell-quoting and no re-splitting. The result is fed to
    ``subprocess.run(argv, shell=False)``, so no shell (cmd.exe/sh) ever re-parses it.
    This is the whole point: one parse here, not three across cmd.exe + sh dialects.
    """
    argv: list[str] = []
    for token in shlex.split(template, posix=True):
        m = _PLACEHOLDER_RE.fullmatch(token)
        if m:
            # A standalone placeholder → the looked-up value as exactly one argv element.
            argv.append(_lookup_template_value(event_data, m.group(1).strip()))
        else:
            # A token that embeds placeholder(s) among other text → substitute inline.
            argv.append(
                _PLACEHOLDER_RE.sub(
                    lambda mm: _lookup_template_value(event_data, mm.group(1).strip()),
                    token,
                )
            )
    return argv


def run_handler(argv: list[str], timeout: int, workdir: str | None) -> bool:
    """Run a handler command (real argv, no shell). Success is exit code 0 before timeout."""
    started = time.monotonic()
    click.echo(f"  Handler start: {argv}")
    try:
        completed = subprocess.run(
            argv,
            cwd=workdir or None,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        click.echo(f"  Handler timeout after {timeout}s", err=True)
        return False
    except OSError as exc:
        click.echo(f"  Handler start failed: {exc}", err=True)
        return False

    elapsed = time.monotonic() - started
    click.echo(f"  Handler exit_code={completed.returncode} duration={elapsed:.1f}s")
    return completed.returncode == 0


@click.group()
@click.option(
    "--url",
    default=None,
    help="Agent Bus server URL (overrides environment and context)",
)
@click.option(
    "--token",
    default=None,
    help="Authentication token (overrides environment and context)",
)
@click.option(
    "--context",
    "context_name",
    default=None,
    help="Use a named context for this command",
)
@click.pass_context
def cli(ctx, url, token, context_name):
    """Agent Bus — cross-machine event relay for AI agents."""
    ctx.ensure_object(dict)
    root, notice = default_context_root()
    ctx.obj["context_store"] = ContextStore(root)
    if notice:
        click.echo(f"Warning: {notice}", err=True)
    ctx.obj["config_inputs"] = {
        "cli_url": url,
        "cli_token": token,
        "context_name": context_name,
        "root": root,
    }


def _command_config(
    ctx,
    *,
    cli_agent: str | None = None,
    resolve_credential: bool = True,
    resolve_agent: bool = True,
) -> RuntimeConfig:
    """Resolve configuration after subcommand flags are available."""
    if "config_inputs" not in ctx.obj:
        return RuntimeConfig(
            url=ctx.obj.get("url", "http://localhost:8800"),
            token=ctx.obj.get("token", ""),
            agent=cli_agent or ctx.obj.get("agent", ""),
            context_name=None,
        )
    inputs = ctx.obj["config_inputs"]
    return resolve_runtime_config(
        cli_url=inputs["cli_url"],
        cli_token=inputs["cli_token"],
        cli_agent=cli_agent,
        context_name=inputs["context_name"],
        root=inputs["root"],
        resolve_credential=resolve_credential,
        resolve_agent=resolve_agent,
    )


def _credential_label(context: dict) -> str:
    credential = context["credential"]
    if credential["type"] == "env":
        return f"env:{credential['name']}"
    return f"env-file:{credential['path']}#{credential['key']}"


@cli.command("setup")
@click.option(
    "--server",
    envvar="AGENT_BUS_SERVER",
    help="Agent Bus server URL (or AGENT_BUS_SERVER)",
)
@click.option(
    "--agent",
    envvar="AGENT_BUS_AGENT",
    help="Agent identity (or AGENT_BUS_AGENT)",
)
@click.option(
    "--name",
    "context_name",
    default=None,
    help="Context name (defaults to the agent identity)",
)
@click.option(
    "--verify/--no-verify",
    default=True,
    show_default=True,
    help="Run connectivity and credential checks after setup",
)
@click.pass_context
def setup_client(ctx, server, agent, context_name, verify):
    """Interactively configure this Mac, Linux, or Windows client."""
    server = server or click.prompt(
        "Agent Bus server URL (for example http://100.x.y.z:8800)"
    )
    agent = agent or click.prompt("Agent name (for example architect or coder)")
    context_name = context_name or agent

    store = ctx.obj["context_store"]
    credential_path = store.root / f"{context_name}.credentials.env"
    token = os.environ.get("AGENT_BUS_CLIENT_TOKEN")

    try:
        validate_context_configuration(
            context_name,
            server=server,
            agent=agent,
            token_env="AGENT_BUS_CLIENT_TOKEN",
            env_file=os.fspath(credential_path),
        )
        if credential_path.exists() and token is None:
            protect_credential_file(credential_path)
            click.echo(f"Reusing protected credential: {credential_path}")
        else:
            token = token or click.prompt(
                f"Token for {agent}",
                hide_input=True,
                confirmation_prompt=False,
            )
            write_credential_file(credential_path, token)
            click.echo(f"Protected credential written: {credential_path}")

        store.add(
            context_name,
            server=server,
            agent=agent,
            token_env="AGENT_BUS_CLIENT_TOKEN",
            env_file=os.fspath(credential_path),
            force=True,
        )
        store.use(context_name)
    except (ContextError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Current context: {context_name}")
    if not verify:
        click.echo("Client setup complete. Run 'agent-bus doctor' when the server is ready.")
        return

    # Verify the context just written, independent of legacy AGENT_BUS_URL,
    # AGENT_BUS_TOKEN, or AGENT_BUS_AGENT values in the caller's environment.
    try:
        config = resolve_runtime_config(
            context_name=context_name,
            env={},
            root=store.root,
        )
    except ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    ctx.obj["config_inputs"] = {
        "cli_url": config.url,
        "cli_token": config.token,
        "context_name": context_name,
        "root": store.root,
    }
    click.echo("Checking server and agent credentials:")
    ctx.invoke(doctor, agent=config.agent, send_test=False, listener=False)


@cli.group("context")
def context_commands():
    """Manage named client connection contexts."""


@context_commands.command("add")
@click.argument("name")
@click.option("--server", required=True, help="Agent Bus server URL")
@click.option("--agent", required=True, help="Agent identity")
@click.option(
    "--token-env",
    required=True,
    help="Credential environment variable, or key when --env-file is used",
)
@click.option(
    "--env-file",
    default=None,
    help="Explicit credential env-file path (never auto-discovered)",
)
@click.option("--select", "select_context", is_flag=True, help="Select after adding")
@click.option("--force", is_flag=True, help="Replace an existing context")
@click.pass_context
def context_add(ctx, name, server, agent, token_env, env_file, select_context, force):
    """Add a token-free named context."""
    store = ctx.obj["context_store"]
    try:
        store.add(
            name,
            server=server,
            agent=agent,
            token_env=token_env,
            env_file=env_file,
            force=force,
        )
        if select_context:
            store.use(name)
    except (ContextError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Context '{name}' saved without credential values.")
    if select_context:
        click.echo(f"Current context: {name}")


@context_commands.command("list")
@click.pass_context
def context_list(ctx):
    """List contexts without resolving or printing credentials."""
    store = ctx.obj["context_store"]
    try:
        current = store.current_name()
        names = store.list_names()
        for name in names:
            context = store.get(name)
            marker = "*" if name == current else " "
            click.echo(
                f"{marker} {name}  {context['server']}  agent={context['agent']}  "
                f"credential={_credential_label(context)}"
            )
    except (ContextError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not names:
        click.echo("No contexts configured.")


@context_commands.command("show")
@click.argument("name", required=False)
@click.pass_context
def context_show(ctx, name):
    """Show one context's connection and credential reference."""
    store = ctx.obj["context_store"]
    try:
        selected = name or store.current_name()
        if selected is None:
            raise ContextError("no context is selected; pass NAME or run context use")
        context = store.get(selected)
        output = {
            "name": selected,
            **context,
            "current": selected == store.current_name(),
        }
    except (ContextError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(output, indent=2, ensure_ascii=False))


@context_commands.command("use")
@click.argument("name")
@click.pass_context
def context_use(ctx, name):
    """Select the default context."""
    try:
        ctx.obj["context_store"].use(name)
    except (ContextError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Current context: {name}")


@context_commands.command("delete")
@click.argument("name")
@click.option(
    "--force", is_flag=True, help="Also delete the currently selected context"
)
@click.pass_context
def context_delete(ctx, name, force):
    """Delete a context without touching its credential source."""
    try:
        ctx.obj["context_store"].delete(name, force=force)
    except (ContextError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Context '{name}' deleted.")


@cli.command("init")
@click.option("--agent", required=True, help="Listener agent/role name")
@click.option("--server-url", required=True, help="Agent Bus server URL")
@click.option(
    "--token-env",
    default=None,
    help="AWF variable containing this agent's token (defaults from --agent)",
)
@click.option(
    "--awf-env",
    type=click.Path(path_type=Path, dir_okay=False),
    default=lambda: Path.home() / ".config" / "awf" / "dispatch.env",
    show_default="~/.config/awf/dispatch.env",
    help="Existing AWF environment containing the role token",
)
@click.option(
    "--repo-dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
@click.option(
    "--script-dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=default_config_path,
    show_default="platform user config/agent-bus/listener.env",
)
@click.option("--warmup-command", default="tailscale", show_default=True)
@click.option("--force", is_flag=True, help="Replace an existing generated config")
def init_listener(
    agent,
    server_url,
    token_env,
    awf_env,
    repo_dir,
    script_dir,
    config_path,
    warmup_command,
    force,
):
    """Create the private, sourceable environment for a workflow listener."""
    for label, path in (
        ("--awf-env", awf_env),
        ("--repo-dir", repo_dir),
        ("--script-dir", script_dir),
    ):
        if not path.expanduser().exists():
            raise click.ClickException(f"{label} does not exist: {path}")
    try:
        content = render_listener_env(
            agent=agent,
            url=server_url,
            awf_env=awf_env.expanduser().resolve(),
            repo_dir=repo_dir.expanduser().resolve(),
            script_dir=script_dir.expanduser().resolve(),
            token_env=token_env,
            warmup_command=warmup_command,
        )
        write_listener_env(config_path, content, force=force)
    except (ValueError, FileExistsError, OSError) as exc:
        if isinstance(exc, FileExistsError):
            message = (
                f"Config already exists: {config_path}. Use --force to replace it."
            )
        else:
            message = str(exc)
        raise click.ClickException(message) from exc
    click.echo(f"Listener config written: {config_path.expanduser()}")
    source_command_path = shell_quote(source_path(config_path.expanduser()))
    click.echo(f"Load it with: source {source_command_path}")
    click.echo("Then run: agent-bus doctor --listener")
    click.echo(
        "Compatibility note: listener.env remains supported; use 'agent-bus context add' "
        "for normal client commands without source/export setup."
    )


@cli.command()
@click.option(
    "--from",
    "from_agent",
    default=None,
    help="Sender agent name",
)
@click.option("--to", "to_agent", required=True, help="Recipient agent name")
@click.option("--type", "event_type", required=True, help="Event type (e.g., task:new)")
@click.option("--payload", default="{}", help="JSON payload string")
@click.option(
    "--payload-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Read JSON payload object from a file",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Validate payload and print the event that would be sent without making an HTTP request",
)
@click.pass_context
def send(ctx, from_agent, to_agent, event_type, payload, payload_file, dry_run):
    """Send an event to another agent."""
    payload_obj = _load_payload(payload, payload_file)
    try:
        config = _command_config(
            ctx,
            cli_agent=from_agent,
            resolve_credential=not dry_run,
        )
    except ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    from_agent = config.agent
    if not from_agent:
        raise click.ClickException(
            "sender agent is not configured; pass --from, set AGENT_BUS_AGENT, "
            "or select a context"
        )

    body = {
        "from_agent": from_agent,
        "to_agent": to_agent,
        "type": event_type,
        "payload": payload_obj,
    }

    if dry_run:
        click.echo(json.dumps(body, indent=2))
        return

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{config.url}/events",
                headers=get_headers(config.token),
                json=body,
            )
            if resp.status_code == 201:
                event = resp.json()
                click.echo(f"Event sent: id={event['id']} status={event['status']}")
                click.echo(json.dumps(event, indent=2))
            else:
                click.echo(f"Error: {resp.status_code} — {resp.text}", err=True)
                sys.exit(1)
    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to {config.url}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("event_id", type=int)
@click.pass_context
def ack(ctx, event_id):
    """Manually acknowledge an event by ID."""
    try:
        config = _command_config(ctx, resolve_agent=False)
    except ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    if not _post_ack(config.url, config.token, event_id):
        sys.exit(1)


def _fetch_event_list(config: RuntimeConfig, agent: str, state: str) -> list[dict]:
    """Fetch one recipient-scoped event list with consistent CLI errors."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{config.url}/events/{state}",
                params={"agent": agent},
                headers=get_headers(config.token),
            )
    except httpx.ConnectError as exc:
        raise click.ClickException(f"Cannot connect to {config.url}") from exc

    if resp.status_code != 200:
        raise click.ClickException(f"{resp.status_code} — {resp.text}")
    return resp.json()


@cli.command()
@click.option("--agent", default=None, help="Agent name to inspect")
@click.option("--count", is_flag=True, help="Print only the number of pending events")
@click.pass_context
def pending(ctx, agent, count):
    """List pending/delivered events for an agent."""
    try:
        config = _command_config(ctx, cli_agent=agent)
    except ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    agent = config.agent
    if not agent:
        raise click.ClickException(
            "agent is not configured; pass --agent, set AGENT_BUS_AGENT, or select a context"
        )
    events = _fetch_event_list(config, agent, "pending")
    if count:
        click.echo(len(events))
    else:
        click.echo(json.dumps(events, indent=2, ensure_ascii=False))


@cli.command()
@click.option("--agent", default=None, help="Agent name to inspect")
@click.option("--count", is_flag=True, help="Print only the number of failed events")
@click.pass_context
def failed(ctx, agent, count):
    """List terminally failed events for an agent."""
    try:
        config = _command_config(ctx, cli_agent=agent)
    except ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    agent = config.agent
    if not agent:
        raise click.ClickException(
            "agent is not configured; pass --agent, set AGENT_BUS_AGENT, or select a context"
        )
    events = _fetch_event_list(config, agent, "failed")
    click.echo(
        len(events) if count else json.dumps(events, indent=2, ensure_ascii=False)
    )


@cli.command()
@click.argument("event_id", type=int)
@click.pass_context
def requeue(ctx, event_id):
    """Requeue one of the current agent's terminally failed events."""
    try:
        config = _command_config(ctx, resolve_agent=False)
    except ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{config.url}/events/{event_id}/requeue",
                headers=get_headers(config.token),
            )
    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to {config.url}", err=True)
        sys.exit(1)

    if resp.status_code != 200:
        click.echo(f"Error: {resp.status_code} — {resp.text}", err=True)
        sys.exit(1)
    event = resp.json()
    click.echo(
        f"Event requeued: id={event['id']} status={event['status']} "
        f"attempts={event['retry_count']}"
    )


@cli.command()
@click.option(
    "--agent",
    default=None,
    help="Agent name to diagnose (defaults from environment or context)",
)
@click.option(
    "--send-test",
    is_flag=True,
    help="Also run a send->pending->ack round-trip self-test (writes a real event)",
)
@click.option(
    "--listener",
    is_flag=True,
    help="Also validate the current AWF/OpenCode listener environment",
)
@click.pass_context
def doctor(ctx, agent, send_test, listener):
    """Diagnose configuration and connectivity to the Agent Bus server.

    Checks, in order: config present, server /health reachable, auth scope
    valid (can list own pending events). With --send-test also performs a
    real send->pending->ack round-trip to the agent itself and cleans up the
    test event. Exits 0 iff all checks pass; non-zero otherwise.
    """
    credential_issue = None
    try:
        config = _command_config(ctx, cli_agent=agent)
    except ContextError as exc:
        credential_issue = str(exc)
        try:
            config = _command_config(
                ctx,
                cli_agent=agent,
                resolve_credential=False,
            )
        except ContextError as config_exc:
            raise click.ClickException(str(config_exc)) from config_exc
    url = config.url
    token = config.token
    agent = config.agent
    total = 3 + int(send_test) + int(listener)
    all_ok = True

    def report(idx, name, passed):
        click.echo(f"[{idx}/{total}] {name}: {'PASS' if passed else 'FAIL'}")

    # --- 1. Config present (URL / token / agent) ---
    config_ok = bool(url and token and agent)
    report(1, "Config", config_ok)
    if not url:
        click.echo(
            "  Server URL is empty. Fix: configure a context or set AGENT_BUS_URL.",
            err=True,
        )
    if not token:
        click.echo(
            "  Token is not available. Fix the selected credential reference or set "
            "AGENT_BUS_TOKEN.",
            err=True,
        )
        if credential_issue:
            click.echo(f"  Credential reference error: {credential_issue}", err=True)
    if not agent:
        click.echo(
            "  Agent is empty. Fix: configure a context or set AGENT_BUS_AGENT.",
            err=True,
        )
    if config_ok:
        click.echo(f"  url={url} agent={agent} token=set")
    all_ok = all_ok and config_ok

    # Without config the remaining checks cannot proceed meaningfully.
    if not config_ok:
        click.echo("\nFix the config above and re-run.", err=True)
        sys.exit(1)

    listener_ok = True
    if listener:
        issues = listener_environment_issues()
        for issue in issues:
            click.echo(f"  {issue}", err=True)
        listener_ok = not issues
        if listener_ok:
            warmup_issue = warm_network_path()
            if warmup_issue:
                click.echo(f"  {warmup_issue}", err=True)
                listener_ok = False
            else:
                click.echo("  listener environment complete; network path warmed")
        report(2, "Listener environment", listener_ok)
        all_ok = all_ok and listener_ok

    headers = get_headers(token)

    # --- 2. Server /health reachable ---
    health_ok = False
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{url}/health")
        if resp.status_code == 200 and resp.json().get("status") == "ok":
            health_ok = True
            click.echo(f"  {url}/health -> status=ok")
        else:
            click.echo(
                f"  {url}/health returned {resp.status_code}: {resp.text[:200]}",
                err=True,
            )
            click.echo(
                "  Fix: ensure the Agent Bus server is running at AGENT_BUS_URL.",
                err=True,
            )
    except httpx.HTTPError as exc:
        click.echo(f"  Cannot reach {url}/health: {exc}", err=True)
        click.echo(
            f"  Fix: check AGENT_BUS_URL and that the server is up (e.g. curl {url}/health).",
            err=True,
        )
    report(2 + int(listener), "Server /health", health_ok)
    all_ok = all_ok and health_ok

    # --- 3. Auth scope valid (can list own pending events) ---
    auth_ok = False
    if health_ok:
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"{url}/events/pending",
                    params={"agent": agent},
                    headers=headers,
                )
            if resp.status_code == 200:
                events = resp.json()
                auth_ok = True
                click.echo(f"  listed {len(events)} pending event(s) for '{agent}'")
            elif resp.status_code == 401:
                click.echo("  401 — token rejected.", err=True)
                click.echo(
                    "  Fix: AGENT_BUS_TOKEN must match the server's AGENT_BUS_TOKEN (legacy) "
                    "or an AGENT_BUS_AGENT_TOKENS entry.",
                    err=True,
                )
            elif resp.status_code == 403:
                click.echo(f"  403 — token not scoped for agent '{agent}'.", err=True)
                click.echo(
                    "  Fix: set AGENT_BUS_AGENT to the agent this token belongs to, or update "
                    "the server's AGENT_BUS_AGENT_TOKENS.",
                    err=True,
                )
            else:
                click.echo(
                    f"  Unexpected {resp.status_code}: {resp.text[:200]}", err=True
                )
        except httpx.HTTPError as exc:
            click.echo(f"  Request error: {exc}", err=True)
    else:
        click.echo("  Skipped (server unreachable).", err=True)
    report(3 + int(listener), "Auth scope", auth_ok)
    all_ok = all_ok and auth_ok

    # --- 4. Optional send->pending->ack round-trip self-test ---
    if send_test:
        idx = 4 + int(listener)
        rt_ok = False
        if not (health_ok and auth_ok):
            click.echo("  Skipped (prior checks failed).", err=True)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            body = {
                "from_agent": agent,
                "to_agent": agent,
                "type": "control:doctor-test",
                "payload": {"_doctor": True, "ts": ts},
            }
            test_event_id = None
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.post(f"{url}/events", headers=headers, json=body)
                    if resp.status_code == 201:
                        test_event_id = resp.json().get("id")
                    else:
                        click.echo(
                            f"  Send failed: {resp.status_code} {resp.text[:200]}",
                            err=True,
                        )

                    if test_event_id is not None:
                        # Verify the event shows up in pending.
                        resp = client.get(
                            f"{url}/events/pending",
                            params={"agent": agent},
                            headers=headers,
                        )
                        ids = (
                            [e.get("id") for e in resp.json()]
                            if resp.status_code == 200
                            else []
                        )
                        seen = test_event_id in ids
                        if not seen:
                            click.echo(
                                f"  Event {test_event_id} not found in pending.",
                                err=True,
                            )

                        # Clean up: ACK the test event.
                        ack_resp = client.post(
                            f"{url}/events/{test_event_id}/ack",
                            params={"agent": agent},
                            headers=headers,
                        )
                        acked = ack_resp.status_code == 200
                        if seen and acked:
                            rt_ok = True
                            click.echo(
                                f"  sent id={test_event_id} -> pending -> acked (cleaned up)"
                            )
                        else:
                            click.echo(
                                f"  round-trip incomplete: seen={seen} acked={acked}",
                                err=True,
                            )
                    else:
                        click.echo(
                            "  No event id returned; cannot complete round-trip.",
                            err=True,
                        )
            except httpx.HTTPError as exc:
                click.echo(f"  Round-trip error: {exc}", err=True)
            if not rt_ok and test_event_id is not None:
                click.echo(f"  Manual cleanup: agent-bus ack {test_event_id}", err=True)
        report(idx, "Round-trip --send-test", rt_ok)
        all_ok = all_ok and rt_ok

    click.echo("")
    if all_ok:
        click.echo("All checks passed.")
        sys.exit(0)
    click.echo("One or more checks failed.", err=True)
    sys.exit(1)


@cli.command()
@click.option("--agent", default=None, help="Agent name to listen as")
@click.option(
    "--on",
    "handlers",
    nargs=2,
    multiple=True,
    metavar="TYPE COMMAND",
    help="Run COMMAND for events of TYPE. ACK happens only on success.",
)
@click.option(
    "--handler-timeout",
    default=3600,
    show_default=True,
    help="Maximum seconds a handler may run before failing",
)
@click.option(
    "--workdir",
    type=click.Path(file_okay=False),
    help="Working directory for handler commands",
)
@click.option(
    "--ack-on-receive",
    is_flag=True,
    help="ACK immediately after printing, without running a handler",
)
@click.option("--once", is_flag=True, help="Process one event and exit")
@click.option(
    "--exit-after-idle",
    default=None,
    type=int,
    help="Exit after N seconds without receiving any events",
)
@click.option(
    "--max-event-attempts",
    default=3,
    type=click.IntRange(min=1),
    show_default=True,
    help="Move an event to terminal failed after N persisted handler failures",
)
@click.option(
    "--ack/--no-ack",
    "legacy_ack",
    default=None,
    hidden=True,
    help="Deprecated; use --ack-on-receive",
)
@click.pass_context
def listen(
    ctx,
    agent,
    handlers,
    handler_timeout,
    workdir,
    ack_on_receive,
    once,
    legacy_ack,
    exit_after_idle,
    max_event_attempts,
):
    """Listen for events via SSE and print them to stdout.

    On connect, receives all un-ACKed events, then waits for new ones.
    Press Ctrl+C to stop.
    """
    try:
        config = _command_config(ctx, cli_agent=agent)
    except ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    agent = config.agent
    if not agent:
        raise click.ClickException(
            "agent is not configured; pass --agent, set AGENT_BUS_AGENT, or select a context"
        )
    token = config.token
    if legacy_ack is not None:
        ack_on_receive = legacy_ack

    handler_map = dict(handlers)
    timeout_config = (
        httpx.Timeout(float(exit_after_idle), connect=30.0) if exit_after_idle else None
    )
    shutdown_requested = False
    url = f"{config.url}/events/stream?agent={agent}"
    headers = {
        **get_headers(token),
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    }

    click.echo(f"Listening for events as '{agent}'...")
    click.echo(f"Server: {config.url}")
    click.echo(f"Handlers: {', '.join(sorted(handler_map)) if handler_map else 'none'}")
    click.echo(f"ACK on receive: {'on' if ack_on_receive else 'off'}")
    click.echo("---")

    completed_ids = set()

    def process_event(event_data: dict) -> bool:
        """Process a received event."""
        event_id = event_data["id"]

        if event_id in completed_ids:
            return False

        # Built-in control:shutdown — ACK and exit gracefully
        if event_data["type"] == "control:shutdown":
            payload = event_data.get("payload", {})
            target = payload.get("target") if isinstance(payload, dict) else None
            if target is not None and target != agent:
                click.echo(
                    f"  control:shutdown target={target} != agent={agent}; ignoring"
                )
                click.echo("")
                return False
            click.echo("  control:shutdown received — shutting down gracefully.")
            acked = _post_ack(
                config.url,
                token,
                event_id,
                event_data.get("retry_count", 0),
            )
            if acked:
                completed_ids.add(event_id)
            nonlocal shutdown_requested
            shutdown_requested = True
            click.echo("")
            return True

        # Timestamp for display
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        payload = event_data.get("payload", {})
        task_id = payload.get("task_id") if isinstance(payload, dict) else None

        click.echo(
            f"[{now}] {event_data['type']} id={event_id} task_id={task_id or '-'}"
        )
        click.echo(f"  From: {event_data['from_agent']} → To: {event_data['to_agent']}")
        click.echo(f"  Status: {event_data['status']}")
        click.echo(
            f"  Payload: {json.dumps(event_data['payload'], ensure_ascii=False)}"
        )
        click.echo("")

        handler = handler_map.get(event_data["type"])
        should_ack = False

        def record_handler_failure(error: str) -> None:
            state = _post_fail(
                config.url,
                token,
                event_id,
                error,
                expected_retry_count=event_data.get("retry_count", 0),
                max_attempts=max_event_attempts,
            )
            if state and state["status"] == "failed":
                completed_ids.add(event_id)
                click.echo(
                    f"  Event {event_id} is terminal failed after "
                    f"{state['retry_count']} attempts; use 'agent-bus failed' "
                    "and 'agent-bus requeue EVENT_ID' to recover it"
                )

        if handler:
            try:
                command = render_command(handler, event_data)
            except KeyError as exc:
                click.echo(f"  Handler template missing field: {exc}", err=True)
                record_handler_failure(f"Handler template missing field: {exc}")
            else:
                should_ack = run_handler(command, handler_timeout, workdir)
                if not should_ack:
                    record_handler_failure("Handler failed")
        elif ack_on_receive:
            should_ack = True
        else:
            click.echo("  No handler configured; leaving event unacked")

        if should_ack and _post_ack(
            config.url,
            token,
            event_id,
            event_data.get("retry_count", 0),
        ):
            completed_ids.add(event_id)
            click.echo("")
            return True

        click.echo("  Event remains unacked")
        click.echo("")
        return False

    # Retry loop for reconnection
    retry_delay = 1
    max_retry_delay = 30

    while True:
        try:
            with httpx.Client(timeout=timeout_config) as client:
                with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code != 200:
                        # `resp` is a streaming response: newer httpx forbids reading
                        # `.text`/`.content` until the body has been consumed with
                        # `read()`. Without this, an error response (e.g. a 4xx during
                        # the SSE handshake) raises "Attempted to access streaming
                        # response content, without having called `read()`" — which was
                        # swallowed as an "Unexpected error" and spun the reconnect loop.
                        resp.read()
                        click.echo(
                            f"Error: Server returned {resp.status_code}: {resp.text}",
                            err=True,
                        )
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, max_retry_delay)
                        continue

                    retry_delay = 1  # Reset on successful connection
                    click.echo("Connected. Waiting for events...")
                    click.echo("")

                    buffer = ""
                    current_event = None

                    for line_bytes in resp.iter_lines():
                        line = (
                            line_bytes.decode("utf-8")
                            if isinstance(line_bytes, bytes)
                            else line_bytes
                        )

                        if line == "":
                            # Empty line = end of event, process it
                            if current_event == "message" and buffer:
                                try:
                                    event_data = json.loads(buffer)
                                    process_event(event_data)
                                    if once or shutdown_requested:
                                        return
                                except json.JSONDecodeError:
                                    click.echo(
                                        f"Warning: could not parse event data: {buffer}",
                                        err=True,
                                    )
                            buffer = ""
                            current_event = None
                            continue

                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                        elif line.startswith("data:"):
                            buffer = line[5:].strip()
                        # else: comment or unknown field, ignore

        except httpx.ReadTimeout:
            click.echo(f"No events received for {exit_after_idle}s; exiting.")
            return
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as e:
            click.echo(
                f"Connection lost: {e}. Reconnecting in {retry_delay}s...", err=True
            )
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
        except KeyboardInterrupt:
            click.echo("\nStopped.")
            break
        except Exception as e:
            click.echo(f"Unexpected error: {e}", err=True)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)


def main():
    """Entry point for the agent-bus CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
