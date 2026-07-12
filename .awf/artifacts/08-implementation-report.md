# Implementation Report — Graceful Exit for `agent-bus listen`

## Task Card

ABUS-EXIT-002 (`.awf/artifacts/07-taskcard-graceful-exit.md`)

## What Changed

**File**: `client/cli.py` only — additive edits, no server/DB/protocol/other command changes.

### Changes Made

1. **`--exit-after-idle` Click option** (line 383–384): added `--exit-after-idle INTEGER` to the `listen` command decorators. Defaults to `None` (no idle limit).

2. **`exit_after_idle` parameter** (line 388): added to the `listen()` function signature.

3. **Timeout config & shutdown flag** (lines 398–399): if `exit_after_idle` is set, `httpx.Timeout(connect=30.0, read=float(exit_after_idle))` is used instead of `timeout=None`. A `shutdown_requested` boolean flag tracks remote shutdown requests.

4. **`control:shutdown` handling** (lines 422–437): in `process_event()`, before any other processing, a check for `type == "control:shutdown"` runs:
   - If payload has `target` and it doesn't match this listener's agent name → ignore (return False, event stays unacked).
   - Otherwise → ACK the event, set `shutdown_requested = True`, return True.

5. **Main loop timeout** (line 480): `httpx.Client(timeout=timeout_config)` — applies the idle read timeout to the SSE stream.

6. **Shutdown check after event** (line 505): `if once or shutdown_requested: return` — exits the loop after the shutdown event is processed.

7. **`httpx.ReadTimeout` handler** (lines 522–524): catches read timeout (no data for `exit_after_idle` seconds), prints message, returns cleanly (exit 0). Placed **before** the existing `ReadError` handler since `ReadTimeout` is a subclass of `ReadError`.

### Not Changed

- `send`, `doctor`, `pending`, `ack` commands — untouched.
- `server/` — untouched.
- DB / wire protocol — untouched.
- Existing `--on` handler mechanism — untouched.
- Ctrl+C handling — preserved.
- No new Python dependencies.

## Verification — Safe Checks

### 1. Existing unit tests pass

```bash
$ .venv/bin/python -m unittest discover -s tests
...
Ran 10 tests in 0.046s
OK
```

### 2. `--exit-after-idle` shown in help

```bash
$ .venv/bin/agent-bus listen --help
...
  --once                     Process one event and exit
  --exit-after-idle INTEGER  Exit after N seconds without receiving any events
  --help                     Show this message and exit.
```

## Remaining Verification (architect to run against a real server)

- **Idle exit**: `agent-bus listen --agent coder --exit-after-idle 5` → exits 0 after ~5s with "No events received for 5s; exiting."
- **Remote shutdown**: send `--type control:shutdown` → listener prints "control:shutdown received — shutting down gracefully.", ACKs, exits 0.
- **Target mismatch**: send `--type control:shutdown --payload '{"target":"someone-else"}'` → listener ignores, keeps running.

## Rework (review ABUS-EXIT-002)

**Bug**: `httpx.Timeout(connect=30.0, read=float(exit_after_idle))` raised `ValueError` because httpx requires either a default timeout or all four parameters (connect/read/write/pool).

**Fix** (`client/cli.py:398`): `httpx.Timeout(float(exit_after_idle), connect=30.0)` — positional arg becomes the default for read/write/pool, connect stays 30s.

**Checks**:
- `unittest discover -s tests`: ✅ 10/10 pass
- `agent-bus listen --help`: ✅ `--exit-after-idle INTEGER` shown
