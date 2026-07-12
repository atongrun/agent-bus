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


def _post_fail(base_url: str, token: str, event_id: int, error: str) -> bool:
    """FAIL an event (server persists it) and print a short diagnostic.

    Never raises out of the listen loop: on network error it prints and
    returns False, mirroring _post_ack.
    """
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{base_url}/events/{event_id}/fail",
                headers=get_headers(token),
                json={"error": error},
            )
    except Exception as exc:
        click.echo(f"  FAIL error: {exc}", err=True)
        return False

    if resp.status_code == 200:
        click.echo("  FAILed (server notified)")
        return True

    click.echo(f"  FAIL failed: {resp.status_code} {resp.text}", err=True)
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
@click.option("--dry-run", is_flag=True,
              help="Validate payload and print the event that would be sent without making an HTTP request")
@click.pass_context
def send(ctx, from_agent, to_agent, event_type, payload, payload_file, dry_run):
    """Send an event to another agent."""
    payload_obj = _load_payload(payload, payload_file)

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
@click.option("--count", is_flag=True,
              help="Print only the number of pending events")
@click.pass_context
def pending(ctx, agent, count):
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
    if count:
        click.echo(len(events))
    else:
        click.echo(json.dumps(events, indent=2, ensure_ascii=False))


@cli.command()
@click.option("--agent", envvar="AGENT_BUS_AGENT",
              required=False, default="",
              help="Agent name to diagnose (defaults to AGENT_BUS_AGENT)")
@click.option("--send-test", is_flag=True,
              help="Also run a send->pending->ack round-trip self-test (writes a real event)")
@click.pass_context
def doctor(ctx, agent, send_test):
    """Diagnose configuration and connectivity to the Agent Bus server.

    Checks, in order: config present, server /health reachable, auth scope
    valid (can list own pending events). With --send-test also performs a
    real send->pending->ack round-trip to the agent itself and cleans up the
    test event. Exits 0 iff all checks pass; non-zero otherwise.
    """
    url = ctx.obj["url"]
    token = ctx.obj["token"]
    total = 4 if send_test else 3
    all_ok = True

    def report(idx, name, passed):
        click.echo(f"[{idx}/{total}] {name}: {'PASS' if passed else 'FAIL'}")

    # --- 1. Config present (URL / token / agent) ---
    config_ok = bool(url and token and agent)
    report(1, "Config", config_ok)
    if not url:
        click.echo("  AGENT_BUS_URL is empty. Fix: export AGENT_BUS_URL=http://<host>:8800", err=True)
    if not token:
        click.echo("  AGENT_BUS_TOKEN is not set. Fix: export AGENT_BUS_TOKEN=<your-token>", err=True)
    if not agent:
        click.echo("  AGENT_BUS_AGENT is not set. Fix: export AGENT_BUS_AGENT=<your-agent>", err=True)
    if config_ok:
        masked = (token[:3] + "***" + token[-2:]) if len(token) > 5 else "***"
        click.echo(f"  url={url} agent={agent} token={masked}")
    all_ok = all_ok and config_ok

    # Without config the remaining checks cannot proceed meaningfully.
    if not config_ok:
        click.echo("\nFix the config above and re-run.", err=True)
        sys.exit(1)

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
            click.echo(f"  {url}/health returned {resp.status_code}: {resp.text[:200]}", err=True)
            click.echo("  Fix: ensure the Agent Bus server is running at AGENT_BUS_URL.", err=True)
    except httpx.HTTPError as exc:
        click.echo(f"  Cannot reach {url}/health: {exc}", err=True)
        click.echo(f"  Fix: check AGENT_BUS_URL and that the server is up (e.g. curl {url}/health).", err=True)
    report(2, "Server /health", health_ok)
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
                click.echo("  Fix: AGENT_BUS_TOKEN must match the server's AGENT_BUS_TOKEN (legacy) "
                           "or an AGENT_BUS_AGENT_TOKENS entry.", err=True)
            elif resp.status_code == 403:
                click.echo(f"  403 — token not scoped for agent '{agent}'.", err=True)
                click.echo("  Fix: set AGENT_BUS_AGENT to the agent this token belongs to, or update "
                           "the server's AGENT_BUS_AGENT_TOKENS.", err=True)
            else:
                click.echo(f"  Unexpected {resp.status_code}: {resp.text[:200]}", err=True)
        except httpx.HTTPError as exc:
            click.echo(f"  Request error: {exc}", err=True)
    else:
        click.echo("  Skipped (server unreachable).", err=True)
    report(3, "Auth scope", auth_ok)
    all_ok = all_ok and auth_ok

    # --- 4. Optional send->pending->ack round-trip self-test ---
    if send_test:
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
                        click.echo(f"  Send failed: {resp.status_code} {resp.text[:200]}", err=True)

                    if test_event_id is not None:
                        # Verify the event shows up in pending.
                        resp = client.get(
                            f"{url}/events/pending",
                            params={"agent": agent},
                            headers=headers,
                        )
                        ids = [e.get("id") for e in resp.json()] if resp.status_code == 200 else []
                        seen = test_event_id in ids
                        if not seen:
                            click.echo(f"  Event {test_event_id} not found in pending.", err=True)

                        # Clean up: ACK the test event.
                        ack_resp = client.post(
                            f"{url}/events/{test_event_id}/ack",
                            params={"agent": agent},
                            headers=headers,
                        )
                        acked = ack_resp.status_code == 200
                        if seen and acked:
                            rt_ok = True
                            click.echo(f"  sent id={test_event_id} -> pending -> acked (cleaned up)")
                        else:
                            click.echo(f"  round-trip incomplete: seen={seen} acked={acked}", err=True)
                    else:
                        click.echo("  No event id returned; cannot complete round-trip.", err=True)
            except httpx.HTTPError as exc:
                click.echo(f"  Round-trip error: {exc}", err=True)
            if not rt_ok and test_event_id is not None:
                click.echo(f"  Manual cleanup: agent-bus ack {test_event_id}", err=True)
        report(4, "Round-trip --send-test", rt_ok)
        all_ok = all_ok and rt_ok

    click.echo("")
    if all_ok:
        click.echo("All checks passed.")
        sys.exit(0)
    click.echo("One or more checks failed.", err=True)
    sys.exit(1)


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
@click.option("--exit-after-idle", default=None, type=int,
              help="Exit after N seconds without receiving any events")
@click.option("--max-event-attempts", default=3, type=int, show_default=True,
              help="Skip an event after N consecutive processing failures (poison event protection)")
@click.option("--ack/--no-ack", "legacy_ack", default=None, hidden=True,
              help="Deprecated; use --ack-on-receive")
@click.pass_context
def listen(ctx, agent, handlers, handler_timeout, workdir, ack_on_receive, once, legacy_ack, exit_after_idle, max_event_attempts):
    """Listen for events via SSE and print them to stdout.

    On connect, receives all un-ACKed events, then waits for new ones.
    Press Ctrl+C to stop.
    """
    if legacy_ack is not None:
        ack_on_receive = legacy_ack

    handler_map = dict(handlers)
    timeout_config = httpx.Timeout(float(exit_after_idle), connect=30.0) if exit_after_idle else None
    shutdown_requested = False
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
    failure_counts = {}
    skipped_ids = set()

    def process_event(event_data: dict) -> bool:
        """Process a received event."""
        event_id = event_data["id"]

        if event_id in completed_ids:
            return False

        if event_id in skipped_ids:
            click.echo(f"  Skipping poison event {event_id} (previously skipped after {max_event_attempts} attempts)")
            return False

        # Built-in control:shutdown — ACK and exit gracefully
        if event_data["type"] == "control:shutdown":
            payload = event_data.get("payload", {})
            target = payload.get("target") if isinstance(payload, dict) else None
            if target is not None and target != agent:
                click.echo(f"  control:shutdown target={target} != agent={agent}; ignoring")
                click.echo("")
                return False
            click.echo("  control:shutdown received — shutting down gracefully.")
            acked = _post_ack(ctx.obj["url"], ctx.obj["token"], event_id)
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
                failure_counts[event_id] = failure_counts.get(event_id, 0) + 1
                if failure_counts[event_id] >= max_event_attempts:
                    _post_fail(ctx.obj["url"], ctx.obj["token"], event_id, f"Handler template missing field: {exc}")
                    skipped_ids.add(event_id)
                    click.echo(f"  Skipping poison event {event_id} after {max_event_attempts} consecutive failed attempts (handler template error)")
            else:
                should_ack = run_handler(command, handler_timeout, workdir)
                if not should_ack:
                    failure_counts[event_id] = failure_counts.get(event_id, 0) + 1
                    if failure_counts[event_id] >= max_event_attempts:
                        _post_fail(ctx.obj["url"], ctx.obj["token"], event_id, f"Handler failed after {max_event_attempts} consecutive attempts")
                        skipped_ids.add(event_id)
                        click.echo(f"  Skipping poison event {event_id} after {max_event_attempts} consecutive failed attempts")
        elif ack_on_receive:
            should_ack = True
        else:
            click.echo("  No handler configured; leaving event unacked")

        if should_ack and _post_ack(ctx.obj["url"], ctx.obj["token"], event_id):
            completed_ids.add(event_id)
            failure_counts.pop(event_id, None)
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
                                    if once or shutdown_requested:
                                        return
                                except json.JSONDecodeError:
                                    click.echo(f"Warning: could not parse event data: {buffer}", err=True)
                                    if current_id is not None:
                                        try:
                                            eid = int(current_id)
                                        except (ValueError, TypeError):
                                            pass
                                        else:
                                            failure_counts[eid] = failure_counts.get(eid, 0) + 1
                                            if failure_counts[eid] >= max_event_attempts:
                                                _post_fail(ctx.obj["url"], ctx.obj["token"], eid, f"JSON decode error after {max_event_attempts} consecutive attempts")
                                                skipped_ids.add(eid)
                                                click.echo(f"  Skipping poison event {eid} after {max_event_attempts} consecutive failed attempts (JSON decode error)")
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

        except httpx.ReadTimeout:
            click.echo(f"No events received for {exit_after_idle}s; exiting.")
            return
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
