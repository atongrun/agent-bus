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
from dotenv import load_dotenv

# Load .env if present
load_dotenv()


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


def _post_ack(base_url: str, token: str, event_id: int) -> bool:
    """ACK an event and print a short diagnostic."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{base_url}/events/{event_id}/ack",
                headers=get_headers(token),
            )
    except Exception as exc:
        click.echo(f"  ACK error: {exc}", err=True)
        return False

    if resp.status_code == 200:
        click.echo("  ACKed")
        return True

    click.echo(f"  ACK failed: {resp.status_code} {resp.text}", err=True)
    return False


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
@click.option("--url", envvar="AGENT_BUS_URL", default="http://localhost:8800",
              help="Agent Bus server URL")
@click.option("--token", envvar="AGENT_BUS_TOKEN", default="",
              help="Authentication token")
@click.pass_context
def cli(ctx, url, token):
    """Agent Bus — cross-machine event relay for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["url"] = url.rstrip("/")
    ctx.obj["token"] = token


@cli.command()
@click.option("--from", "from_agent", envvar="AGENT_BUS_AGENT",
              required=True, help="Sender agent name")
@click.option("--to", "to_agent", required=True, help="Recipient agent name")
@click.option("--type", "event_type", required=True, help="Event type (e.g., task:new)")
@click.option("--payload", default="{}", help="JSON payload string")
@click.option("--payload-file", type=click.Path(exists=True, dir_okay=False),
              help="Read JSON payload object from a file")
@click.pass_context
def send(ctx, from_agent, to_agent, event_type, payload, payload_file):
    """Send an event to another agent."""
    payload_obj = _load_payload(payload, payload_file)

    body = {
        "from_agent": from_agent,
        "to_agent": to_agent,
        "type": event_type,
        "payload": payload_obj,
    }

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{ctx.obj['url']}/events",
                headers=get_headers(ctx.obj["token"]),
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
        click.echo(f"Error: Cannot connect to {ctx.obj['url']}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("event_id", type=int)
@click.pass_context
def ack(ctx, event_id):
    """Manually acknowledge an event by ID."""
    if not _post_ack(ctx.obj["url"], ctx.obj["token"], event_id):
        sys.exit(1)


@cli.command()
@click.option("--agent", envvar="AGENT_BUS_AGENT",
              required=True, help="Agent name to inspect")
@click.pass_context
def pending(ctx, agent):
    """List pending/delivered events for an agent."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{ctx.obj['url']}/events/pending",
                params={"agent": agent},
                headers=get_headers(ctx.obj["token"]),
            )
    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to {ctx.obj['url']}", err=True)
        sys.exit(1)

    if resp.status_code != 200:
        click.echo(f"Error: {resp.status_code} — {resp.text}", err=True)
        sys.exit(1)

    events = resp.json()
    click.echo(json.dumps(events, indent=2, ensure_ascii=False))


@cli.command()
@click.option("--agent", envvar="AGENT_BUS_AGENT",
              required=True, help="Agent name to listen as")
@click.option("--on", "handlers", nargs=2, multiple=True,
              metavar="TYPE COMMAND",
              help="Run COMMAND for events of TYPE. ACK happens only on success.")
@click.option("--handler-timeout", default=3600, show_default=True,
              help="Maximum seconds a handler may run before failing")
@click.option("--workdir", type=click.Path(file_okay=False),
              help="Working directory for handler commands")
@click.option("--ack-on-receive", is_flag=True,
              help="ACK immediately after printing, without running a handler")
@click.option("--once", is_flag=True,
              help="Process one event and exit")
@click.option("--ack/--no-ack", "legacy_ack", default=None, hidden=True,
              help="Deprecated; use --ack-on-receive")
@click.pass_context
def listen(ctx, agent, handlers, handler_timeout, workdir, ack_on_receive, once, legacy_ack):
    """Listen for events via SSE and print them to stdout.

    On connect, receives all un-ACKed events, then waits for new ones.
    Press Ctrl+C to stop.
    """
    if legacy_ack is not None:
        ack_on_receive = legacy_ack

    handler_map = dict(handlers)
    url = f"{ctx.obj['url']}/events/stream?agent={agent}"
    headers = {
        **get_headers(ctx.obj["token"]),
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    }

    click.echo(f"Listening for events as '{agent}'...")
    click.echo(f"Server: {ctx.obj['url']}")
    click.echo(f"Handlers: {', '.join(sorted(handler_map)) if handler_map else 'none'}")
    click.echo(f"ACK on receive: {'on' if ack_on_receive else 'off'}")
    click.echo("---")

    completed_ids = set()

    def process_event(event_data: dict) -> bool:
        """Process a received event."""
        event_id = event_data["id"]

        if event_id in completed_ids:
            return False

        # Timestamp for display
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        payload = event_data.get("payload", {})
        task_id = payload.get("task_id") if isinstance(payload, dict) else None

        click.echo(f"[{now}] {event_data['type']} id={event_id} task_id={task_id or '-'}")
        click.echo(f"  From: {event_data['from_agent']} → To: {event_data['to_agent']}")
        click.echo(f"  Status: {event_data['status']}")
        click.echo(f"  Payload: {json.dumps(event_data['payload'], ensure_ascii=False)}")
        click.echo("")

        handler = handler_map.get(event_data["type"])
        should_ack = False

        if handler:
            try:
                command = render_command(handler, event_data)
            except KeyError as exc:
                click.echo(f"  Handler template missing field: {exc}", err=True)
            else:
                should_ack = run_handler(command, handler_timeout, workdir)
        elif ack_on_receive:
            should_ack = True
        else:
            click.echo("  No handler configured; leaving event unacked")

        if should_ack and _post_ack(ctx.obj["url"], ctx.obj["token"], event_id):
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
            with httpx.Client(timeout=None) as client:
                with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code != 200:
                        click.echo(f"Error: Server returned {resp.status_code}: {resp.text}", err=True)
                        time.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, max_retry_delay)
                        continue

                    retry_delay = 1  # Reset on successful connection
                    click.echo("Connected. Waiting for events...")
                    click.echo("")

                    buffer = ""
                    current_id = None
                    current_event = None

                    for line_bytes in resp.iter_lines():
                        line = line_bytes.decode("utf-8") if isinstance(line_bytes, bytes) else line_bytes

                        if line == "":
                            # Empty line = end of event, process it
                            if current_event == "message" and buffer:
                                try:
                                    event_data = json.loads(buffer)
                                    process_event(event_data)
                                    if once:
                                        return
                                except json.JSONDecodeError:
                                    click.echo(f"Warning: could not parse event data: {buffer}", err=True)
                            buffer = ""
                            current_id = None
                            current_event = None
                            continue

                        if line.startswith("id:"):
                            current_id = line[3:].strip()
                        elif line.startswith("event:"):
                            current_event = line[6:].strip()
                        elif line.startswith("data:"):
                            buffer = line[5:].strip()
                        # else: comment or unknown field, ignore

        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as e:
            click.echo(f"Connection lost: {e}. Reconnecting in {retry_delay}s...", err=True)
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
