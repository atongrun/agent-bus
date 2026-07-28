# TaskCard: Redact payloads for unmatched listener events

## Objective

Prevent a handler-driven `agent-bus listen` process from exposing the raw payload of an event whose
type has no configured handler. Preserve the event, ACK state, retry state, SSE protocol, and manual
inspection behavior.

## Evidence

Agent Workflow started a coder listener with only `task:awf-impl-v2` configured. Agent Bus replayed a
preserved legacy `task:awf-impl` event to the same identity, printed its complete payload, found no
matching handler, and correctly left it unacknowledged. The payload exposure blocks a workflow that
must preserve legacy event contents without reading them.

No historical event may be ACKed, failed, requeued, deleted, or otherwise mutated during this fix.

## Allowed Changes

1. `client/cli.py`
2. `tests/test_poison_event.py`
3. `CHANGELOG.md`
4. `docs/tasks/unhandled-listener-payload-redaction-report.md`

Do not modify this TaskCard after it is committed. Do not change server APIs, database state,
authentication, event delivery, ACK/fail/requeue semantics, dependencies, deployment, or Workflow.

## Required Behavior

- When one or more `--on` handlers are configured and the received event type has no matching
  handler, do not inspect `payload.task_id` for display and do not serialize or print the payload.
- Print safe event metadata plus a stable redaction marker and the existing unhandled/unacknowledged
  message.
- Do not run a handler, ACK, record failure, requeue, or mark the unmatched event completed.
- A matching handler keeps the existing payload display and execution behavior.
- A manual listener with no handler map keeps the existing raw payload display behavior.
- Explicit `--ack-on-receive` keeps its existing payload display and ACK behavior.
- Document the safer handler-driven display behavior under `Unreleased`.

## Verification

```bash
python -m pytest -q tests/test_poison_event.py
python -m pytest -q
ruff check client server tests
ruff format --check client server tests
python -m compileall -q client server tests
git diff --check
```

Run the focused listener tests on Windows at the final exact head. Before merge, a fresh independent
Codex subagent must review the final head, then the main agent must independently double-check the
same head. GitHub CI must pass.

## Rollout

After merge, install/activate the exact version on Mac, Windows, and VPS without changing server
storage. Re-run an unmatched-event listener probe only if it can prove no payload is printed and no
event state changes. Then resume the Dousansi product loop with v2 listeners.

## Stop Conditions

- Stop if the fix requires mutating the preserved event or changing protocol/database semantics.
- Stop if unmatched events can still reach handler argv, stdout/stderr, logs, or failure accounting.
- Stop if matched-handler or manual-inspection behavior regresses.
