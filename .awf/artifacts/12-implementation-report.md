# Implementation Report — Poison Event Protection for `agent-bus listen`

## Task Card

ABUS-POISON-003 (`.awf/artifacts/11-taskcard-poison-event.md`)

## What Changed

**File**: `client/cli.py` only — additive edits, no server/DB/protocol/other command changes.

### Changes Made

1. **`--max-event-attempts` Click option**: added after `--exit-after-idle` in the `listen` command decorators. Defaults to `3`, shown in `--help` via `show_default=True`. Help text: "Skip an event after N consecutive processing failures (poison event protection)".

2. **`max_event_attempts` parameter**: added to the `listen()` function signature.

3. **Tracking structures** (`failure_counts` dict, `skipped_ids` set): added alongside the existing `completed_ids` set, with the same closure lifecycle. `failure_counts` maps event id → consecutive failure count. `skipped_ids` tracks event ids that have reached the threshold.

4. **`skipped_ids` early-return in `process_event`**: after the `completed_ids` check, if `event_id in skipped_ids`, prints `"Skipping poison event {id} (previously skipped after {N} attempts)"` and returns False without running the handler.

5. **Failure tracking on handler template KeyError**: when `render_command` raises `KeyError` (handler template references a missing event field), increments `failure_counts[event_id]`. If count reaches `max_event_attempts`, adds to `skipped_ids` and prints `"Skipping poison event {id} after {N} consecutive failed attempts (handler template error)"`.

6. **Failure tracking on handler non-zero exit**: after `run_handler` returns False (handler completed with non-zero exit code), increments `failure_counts[event_id]`. If count reaches threshold, adds to `skipped_ids` and prints `"Skipping poison event {id} after {N} consecutive failed attempts"`.

7. **Failure count cleared on success**: when an event is successfully processed and ACKed, `failure_counts.pop(event_id, None)` resets the counter so a transient failure doesn't permanently burn an event's attempts.

8. **Failure tracking on JSON decode error**: in the SSE loop, when `json.loads(buffer)` raises `JSONDecodeError`, uses the SSE `id:` field (`current_id`) to track consecutive failures. If count reaches threshold, adds to `skipped_ids` with message `"Skipping poison event {id} after {N} consecutive failed attempts (JSON decode error)"`.

### Not Changed

- `send`, `doctor`, `pending`, `ack` commands — untouched.
- `server/` — untouched.
- DB / wire protocol — untouched.
- How successful events are ACKed — untouched.
- Reconnect/backoff logic — untouched.
- `control:shutdown`/`--exit-after-idle`/`--once` behavior — untouched.
- Ctrl+C handling — preserved.
- No new Python dependencies.

### Deviation from Card

- **Skip-without-ACK approach**: When an event is added to `skipped_ids`, the listener stops running its handler but does NOT ACK the event. This matches the card's preference (risk row: "Prefer skip-without-ACK; document the choice; leave it inspectable."). The event remains unacked and viewable via `agent-bus pending` for human inspection / `agent-bus ack`.
- On subsequent redeliveries of a skipped event, a brief log line is printed (`"Skipping poison event {id} (previously skipped after {N} attempts)"`) to keep the operator informed, whereas the card only specified the initial skip message.

## Verification — Safe Checks

### 1. Existing unit tests pass

```bash
$ .venv/bin/python -m unittest discover -s tests
....  Handler start: ... Handler exit_code=0 duration=0.0s
  Handler start: ... Handler exit_code=3 duration=0.0s
......
----------------------------------------------------------------------
Ran 10 tests in 0.048s
OK
```

### 2. `--max-event-attempts` shown in help

```bash
$ .venv/bin/agent-bus listen --help
...
  --exit-after-idle INTEGER     Exit after N seconds without receiving any
                                events
  --max-event-attempts INTEGER  Skip an event after N consecutive processing
                                failures (poison event protection)  [default:
                                3]
  --help                        Show this message and exit.
```

## Remaining Verification (architect to run against a real server)

- **Poison simulation**: `agent-bus listen --agent coder --on 'task:new python -c "raise SystemExit(1)"' --max-event-attempts 3` → with a malformed event, listener should attempt 3 times, then print "Skipping poison event {id} after 3 consecutive failed attempts" and stop re-running the handler on subsequent redeliveries.
- **Reset on success**: after 2 failures, a corrected event should be processed successfully, and failure count should reset.
- **Normal events unaffected**: a working handler should still handle+ACK events without any poison tracking interference.

## Acceptance Criteria Checklist

- [x] `agent-bus listen --help` shows `--max-event-attempts` with default 3.
- [x] Existing unit tests pass (10/10 OK).
- [x] `send` / `doctor` / `pending` / `ack` / `control:shutdown` / `--exit-after-idle` unchanged.
- [ ] (Live) Simulated poison event skipped after threshold.
- [ ] (Live) Normal event handled and ACKed without regression.
