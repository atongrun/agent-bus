# TaskCard: Recover unacknowledged events after a stale SSE stream

## Objective

Make a daemon `agent-bus listen` reconnect after a bounded idle read timeout so the server can replay
persisted `pending` or `delivered` events. Preserve protocol, storage, handler, ACK, failure, requeue,
manual-listener, and explicit `--exit-after-idle` behavior.

## Evidence

A live, goal-created event was marked `delivered` at creation but produced no handler RunEvidence,
model/Git process, branch change, ACK, or failed-attempt transition on the connected Windows client.
An isolated state-machine reproduction proved that the active stream's high-water excludes the row,
while a reconnect includes the same unacknowledged `delivered` row in initial replay.

Historical event payloads and listener logs are outside scope. Do not ACK, fail, or requeue any live
event while implementing or testing this change.

## Allowed Changes

1. `client/cli.py`
2. `tests/test_poison_event.py`
3. `CHANGELOG.md`
4. `docs/tasks/sse-idle-reconnect-report.md`

## Required Behavior

- Default daemon listeners use a bounded read timeout and reconnect after timeout with existing
  bounded backoff.
- Reconnect uses the existing initial replay and does not introduce claims, leases, or new protocol
  state.
- Explicit `--exit-after-idle N` still exits after `N` idle seconds without reconnecting.
- A replayed event invokes its matching handler once in the acceptance scenario and ACKs only after
  handler success.
- No dependency, server API, database, payload display, ACK/fail, or requeue behavior changes.

## Verification

```bash
python -m pytest -q tests/test_poison_event.py
AGENT_BUS_URL=http://localhost:8800 python -m pytest -q
ruff check --select E4,E7,E9,F client server tests
ruff format --check client/cli.py tests/test_poison_event.py
python -m compileall -q client server tests
git diff --check
```

Run the focused tests plus static gates from a fresh Windows exact-head checkout. Before merge, a
fresh independent Codex subagent must review the exact head, followed by a main-agent double-check and
successful GitHub CI.

## Rollout

Activate the exact merged client commit on Mac and Windows. The VPS server does not need an upgrade
because this is client-only. Restart exactly one listener per identity, verify stale delivered-event
replay with safe metadata/artifact evidence, then resume the product loop.
