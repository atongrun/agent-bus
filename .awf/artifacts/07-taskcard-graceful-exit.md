# Task Card

## Task ID

ABUS-EXIT-002

## Background

Real use surfaced a pain point (Baseline P3): the `listen` service only exits via `--once`
or Ctrl+C. It does not follow the parent tool's exit and cannot be stopped remotely, so
listener processes linger. The operator's intended workflow: **Hermes (on the VPS) sends a
control event to stop a machine's listener**, and the listener exits cleanly on its own.
Architecture is frozen for this milestone (see `.awf/artifacts/02-architecture-decision.md`;
P3 direction). Executor for this card: **OpenCode running DeepSeek V4 Flash**.

## Goal

Give `agent-bus listen` two graceful-exit mechanisms: (1) auto-exit after an idle period,
and (2) remote exit when it receives a `control:shutdown` event addressed to its agent — so
Hermes can stop a listener by sending one event.

## Scope

- Add `--exit-after-idle <seconds>` option to the `listen` command: if no event is received
  for that many seconds, the listener prints a message and exits 0.
- Handle a built-in event type `control:shutdown`: when received, the listener ACKs it,
  prints a message, and exits 0 (graceful shutdown). This works **without** the user having
  to configure a `--on control:shutdown` handler.
- `control:shutdown` payload may carry an optional `target` field. If `target` is present
  and does **not** equal this listener's agent name, the shutdown is **ignored** (event left
  for the intended target). If `target` is absent or matches, the listener shuts down.
  (This reserves the interface for future per-machine addressing without implementing it.)

## Out of Scope

- No per-machine / per-instance identity beyond the optional `target` name-match above. Do
  NOT add `--instance-id`, worker registries, or lease/claim semantics (those are Later P2).
- No changes to `server/`, the DB schema, or the wire protocol. `control:shutdown` is just a
  normal event with a conventional `type` — the server already relays arbitrary types.
- Do NOT change `send`, `doctor`, `pending`, `ack`, or the existing `--on` handler mechanism.
- No new Python dependencies.

## Working Context (self-contained)

- **Repository / path**: `<agent-bus-repo>`
- **File to edit**: `client/cli.py` (the whole CLI lives here).
- **Command to modify**: `listen`, defined at `client/cli.py:386` (decorator block starts
  ~`:369`). Add the new `--exit-after-idle` Click option alongside the existing ones
  (`--once` is at `:381`, `--handler-timeout` at `:375` — copy their style).
- **Event handling happens in** the nested `process_event(event_data) -> bool` at
  `client/cli.py:411`. `event_data["type"]` is the event type; `event_data["payload"]` is a
  dict; `event_data["id"]` is the id. `_post_ack(ctx.obj["url"], ctx.obj["token"], id)` ACKs
  an event (used at `:444`). Returning from `process_event` does not itself stop the loop.
- **The main receive loop** is the `while True:` at `:457`. Inside, the SSE stream is read
  line-by-line (`for line in resp.iter_lines():` ~`:320`-style in the same function); a
  completed event triggers `process_event(...)`, and `--once` exits via `if once: return`
  (see the `doctor`-adjacent `listen` body; the `once` return is the model to follow for a
  clean exit — use `return` out of `listen`, not `sys.exit`, to match existing style).
- **Idle timing**: the stream read blocks waiting for lines. To implement idle-exit without
  new deps, use the existing `httpx` stream timeout: the loop already runs with
  `httpx.Client(timeout=None)` at `:459`. A simple approach: track `last_event_time` and, on
  each reconnect/loop iteration or via httpx read timeout, compare elapsed vs the idle limit.
  Keep it simple; a coarse idle check (e.g. set the httpx read timeout to the idle value and
  treat a read timeout as "idle elapsed → exit 0") is acceptable.
- **Signal to exit cleanly**: printing a short message then `return` from `listen` ends the
  process with exit 0 (Click command returns normally). Ctrl+C handling at `:350` already
  exists — do not remove it.
- **Project rules**: see `AGENTS.md` if present; else follow this file's style (4-space
  indent, Click decorators, `httpx`, `click.echo`, `_post_ack` for ACK).

## Constraints

- Additive only: no server/DB/protocol change; `control:shutdown` is a plain event type.
- `control:shutdown` must be ACK'd before exit (so it doesn't replay to a future listener).
- Default behavior unchanged: without `--exit-after-idle` and without a `control:shutdown`
  event, `listen` behaves exactly as today (runs until Ctrl+C).
- `control:shutdown` handling must NOT require the user to pass `--on control:shutdown`.
- Idle-exit and shutdown-exit both exit with code 0 (clean stop, not an error).
- No new dependencies.

## Acceptance Criteria

- [ ] `agent-bus listen --help` shows the new `--exit-after-idle` option.
- [ ] With `--exit-after-idle 5` and no events, the listener exits 0 within a few seconds
      past the idle window, printing an idle-exit message.
- [ ] Sending an event of type `control:shutdown` to the listener's agent causes it to print
      a shutdown message, ACK that event, and exit 0 — **without** any `--on` handler for it.
- [ ] A `control:shutdown` whose payload `target` names a *different* agent is ignored (the
      listener keeps running); one with no `target` or a matching `target` shuts it down.
- [ ] Normal handler behavior is unchanged: a `--on task:x "cmd"` still runs and ACKs on
      success; unrelated events without handlers are still left unacked as before.
- [ ] Existing unit tests still pass: `.venv/bin/python -m unittest discover -s tests` → OK.
- [ ] `send` / `doctor` / `pending` / `ack` unchanged in behavior.

## Verification Commands

```bash
cd <agent-bus-repo>

# 1) existing tests stay green
.venv/bin/python -m unittest discover -s tests

# 2) help shows the new option
.venv/bin/agent-bus listen --help    # expect: --exit-after-idle

# 3) idle-exit: no events for 5s -> exits 0
AGENT_BUS_URL=$AGENT_BUS_URL \
AGENT_BUS_TOKEN=<coder-token> AGENT_BUS_AGENT=coder \
  .venv/bin/agent-bus listen --agent coder --exit-after-idle 5 ; echo "exit=$?"

# 4) remote graceful shutdown: in terminal A start a listener; in terminal B send shutdown.
#    Terminal A (listener, no idle limit):
AGENT_BUS_URL=$AGENT_BUS_URL \
AGENT_BUS_TOKEN=<coder-token> AGENT_BUS_AGENT=coder \
  .venv/bin/agent-bus listen --agent coder ; echo "exit=$?"
#    Terminal B (Hermes's role — send the stop event):
AGENT_BUS_URL=$AGENT_BUS_URL \
AGENT_BUS_TOKEN=<architect-token> AGENT_BUS_AGENT=architect \
  .venv/bin/agent-bus send --from architect --to coder --type control:shutdown --payload '{}'
#    Expect: terminal A prints shutdown msg, ACKs, exits 0.

# 5) target-mismatch is ignored (listener keeps running):
#    ... send --type control:shutdown --payload '{"target":"someone-else"}'  -> listener stays up.
```

> The executor should read the coder/architect token from the environment/.env already on
> this machine or ask the operator — do NOT hardcode a token into the source.

## Rework vs. Escalate

- **Rework locally** only for deterministic failures: a failing acceptance criterion, a
  traceback, tests going red, or a clear violation of this card.
- **Escalate (stop and report)** if: implementing idle-exit cleanly seems to require a
  server/protocol change (it should not — if it does, stop), config/token is unavailable, or
  an acceptance criterion is ambiguous.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Idle-exit implementation busy-waits or blocks forever | Medium | Reuse httpx read-timeout; treat read timeout as idle-elapsed; keep the check coarse. |
| `control:shutdown` not ACK'd → replays and kills the next listener too | Medium | ACK the shutdown event before returning (criterion + constraint). |
| Breaking the existing SSE receive loop / `--once` / Ctrl+C paths | Medium | Additive edits only; preserve existing `return`/KeyboardInterrupt branches. |
| target-match logic accidentally drops normal events | Low | Only apply target logic to `type == "control:shutdown"`. |

## Required Output Artifacts

- ImplementationReport: what changed in `client/cli.py`, the exact verification commands run,
  their output (including exit codes), and any deviation from this card.

---

## Planner Self-Check (completed before delegation)

- [x] Goal is a single milestone (graceful exit: idle + remote shutdown).
- [x] Scope and Out of Scope explicit; instance-addressing explicitly deferred to `target` name-match only.
- [x] Every acceptance criterion is verifiable by a command or observable check.
- [x] Verification commands use the project's real commands, confirmed against the codebase.
- [x] Working Context has file + line anchors (listen@386, process_event@411, loop@457, ack@444) so a fresh-session executor can start without this chat.
- [x] Advances the chosen milestone (P3); no unrelated refactors; P2/P4 stay Later.
- [x] Hermes "stop a machine's listener" scenario explicitly covered (control:shutdown + optional target).
