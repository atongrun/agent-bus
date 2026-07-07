#!/usr/bin/env bash
set -euo pipefail

python3 - "$@" <<'PY'
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

url = os.environ.get("AGENT_BUS_URL", "").rstrip("/")
token = os.environ.get("AGENT_BUS_TOKEN", "")
agent = os.environ.get("AGENT_BUS_AGENT", "mac-codex")
review_script = os.environ.get("AGENT_BUS_REVIEW_SCRIPT", "")
poll_seconds = float(os.environ.get("AGENT_BUS_POLL_SECONDS", "2"))
once = "--once" in sys.argv

if not url:
    raise SystemExit("AGENT_BUS_URL is required")
if not token:
    raise SystemExit("AGENT_BUS_TOKEN is required")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}


def request(method, path, body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        f"{url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")
        if not raw:
            return None
        return json.loads(raw)


def ack(event_id):
    request("POST", f"/events/{event_id}/ack")
    print(f"ACK id={event_id}", flush=True)


def run_review(payload):
    if not review_script:
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        print(f"review placeholder: {rendered}", flush=True)
        return 0

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        payload_path = handle.name

    try:
        completed = subprocess.run([review_script, payload_path], check=False)
        return completed.returncode
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass


print(f"Agent Bus Mac review listener agent={agent} url={url}", flush=True)

while True:
    encoded_agent = urllib.parse.quote(agent, safe="")
    try:
        events = request("GET", f"/events/pending?agent={encoded_agent}") or []
    except urllib.error.URLError as exc:
        print(f"poll error: {exc}", file=sys.stderr, flush=True)
        if once:
            raise
        time.sleep(poll_seconds)
        continue

    for event in events:
        payload = event.get("payload") or {}
        task_id = payload.get("task_id", "") if isinstance(payload, dict) else ""
        event_type = event.get("type")
        event_id = event.get("id")
        print(f"event id={event_id} type={event_type} task_id={task_id}", flush=True)

        if event_type != "task:completed":
            print(f"skip id={event_id}: no handler for type={event_type}", flush=True)
            continue

        exit_code = run_review(payload)
        print(f"review exit_code={exit_code}", flush=True)
        if exit_code == 0:
            ack(event_id)
        else:
            print(f"leave unacked id={event_id}", flush=True)

    if once:
        break
    time.sleep(poll_seconds)
PY
