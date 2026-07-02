"""Agent Bus CLI — send and listen for agent events."""

import json
import os
import sys
import time
from datetime import datetime, timezone

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
@click.pass_context
def send(ctx, from_agent, to_agent, event_type, payload):
    """Send an event to another agent."""
    try:
        payload_obj = json.loads(payload)
    except json.JSONDecodeError:
        click.echo("Error: --payload must be valid JSON", err=True)
        sys.exit(1)

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
@click.option("--agent", envvar="AGENT_BUS_AGENT",
              required=True, help="Agent name to listen as")
@click.option("--ack/--no-ack", default=True,
              help="Auto-ACK events after receiving (default: --ack)")
@click.pass_context
def listen(ctx, agent, ack):
    """Listen for events via SSE and print them to stdout.

    On connect, receives all un-ACKed events, then waits for new ones.
    Press Ctrl+C to stop.
    """
    url = f"{ctx.obj['url']}/events/stream?agent={agent}&token={ctx.obj['token']}"
    headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    }

    click.echo(f"Listening for events as '{agent}'...")
    click.echo(f"Server: {ctx.obj['url']}")
    click.echo(f"Auto-ACK: {'on' if ack else 'off'}")
    click.echo("---")

    seen_ids = set()

    def process_event(event_data: dict):
        """Process a received event."""
        event_id = event_data["id"]

        # Deduplicate
        if event_id in seen_ids:
            return
        seen_ids.add(event_id)

        # Timestamp for display
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")

        click.echo(f"[{now}] {event_data['type']}")
        click.echo(f"  From: {event_data['from_agent']} → To: {event_data['to_agent']}")
        click.echo(f"  ID: {event_id}  Status: {event_data['status']}")
        click.echo(f"  Payload: {json.dumps(event_data['payload'])}")
        click.echo("")

        # Auto-ACK if enabled
        if ack:
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.post(
                        f"{ctx.obj['url']}/events/{event_id}/ack",
                        headers=get_headers(ctx.obj["token"]),
                    )
                    if resp.status_code == 200:
                        click.echo(f"  ✓ ACKed")
                    else:
                        click.echo(f"  ✗ ACK failed: {resp.status_code}")
            except Exception as e:
                click.echo(f"  ✗ ACK error: {e}")
            click.echo("")

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
