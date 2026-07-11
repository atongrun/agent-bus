# Task Card

## Task ID

ABUS-POISON-003

## Background

During real dogfood, a single bad event crash-looped the listener: an event whose handler
failed (or whose data was malformed) never got ACKed, so on every SSE reconnect the server
re-delivered the SAME event, the handler failed again, and the listener spun forever
processing only that one "poison" event — starving all real work. Mature queues protect
against this ("poison message" / dead-letter). Agent Bus has no such protection today.

## Goal

Make the `listen` command resilient to a poison event: if the same event fails to be
processed successfully N times in a row, the listener stops retrying that specific event
(skips it and moves on), instead of re-processing it forever.

## Scope

- In `client/cli.py`, track per-event consecutive failure counts in the listener.
- When an event's processing fails (handler non-zero, template KeyError, or JSON decode
  error for that event), increment its failure count.
- When a single event id reaches a threshold (default 3, add `--max-event-attempts N`
  option), the listener prints a clear "skipping poison event <id> after N attempts"
  message and stops re-processing it (add it to a skip set so future redeliveries are
  ignored without running the handler).
- Successful processing of an event clears its failure count.

## Out of Scope

- No server/DB/protocol change. This is client-side only. (Server-side dead-letter is a
  separate future task.)
- Do NOT change how successful events are ACKed, or the reconnect/backoff logic.
- Do NOT change `send`, `doctor`, `pending`, `ack`, or the `control:shutdown`/idle-exit
  behavior added earlier.
- No new dependencies.

## Working Context (self-contained)

- **Repository / path**: the repo root you are running in (the agent-bus checkout).
- **File to edit**: `client/cli.py` only.
- **Where processing happens**: nested `process_event(event_data) -> bool` inside the
  `listen` command (around `client/cli.py:411`+). It returns True when the event was
  handled+ACKed, False otherwise. The current failure paths that leave an event un-ACKed:
  - handler template KeyError (~`:456-457`)
  - handler ran but returned non-zero -> `should_ack` stays False (~`:459`, `:470`)
  - JSON decode error in the SSE loop (~ the `except json.JSONDecodeError` branch)
- **The receive loop**: `while True:` (~`:478`), reads SSE lines, calls `process_event`.
  Same event id can arrive repeatedly across reconnects; `completed_ids` already tracks
  successfully-handled ids (`:415-416` early-returns if already completed). Add a parallel
  `failure_counts` dict and a `skipped_ids` set with the same lifecycle.
- **Style**: 4-space indent, `click.echo(...)` / `click.echo(..., err=True)`; add the new
  option next to `--exit-after-idle` (~`:383`) following the same decorator pattern.
- **Project rules**: follow this file's existing conventions.

## Constraints

- Client-side only; additive; no new deps.
- Default threshold 3; overridable via `--max-event-attempts`.
- A skipped poison event must NOT be ACKed silently unless you are sure — prefer: stop
  running its handler and stop counting it as blocking, but leave it for a human/`doctor`
  to inspect. (Document whichever you choose in the report.)
- Real handler success must reset that event's counter (a transient failure shouldn't
  permanently burn an event's attempts across a later success).

## Acceptance Criteria

- [ ] `agent-bus listen --help` shows `--max-event-attempts`.
- [ ] Simulated poison event: with a handler that always exits non-zero, the listener
      attempts it up to the threshold, prints a "skipping poison event" message, then
      does NOT keep re-running the handler for that id on subsequent redeliveries.
- [ ] A normal event with a succeeding handler is still handled and ACKed as before
      (no regression), and its failure counter behavior doesn't affect it.
- [ ] Existing unit tests pass: `.venv/bin/python -m unittest discover -s tests` -> OK.
- [ ] `send` / `doctor` / `pending` / `ack` / `control:shutdown` / `--exit-after-idle`
      unchanged.

## Verification Commands

```bash
cd <repo>   # the agent-bus checkout

# 1) existing tests stay green
.venv/bin/python -m unittest discover -s tests

# 2) help shows the new option
.venv/bin/agent-bus listen --help    # expect: --max-event-attempts

# 3) (reviewer, against VPS) poison simulation: a handler that always fails
#    should be attempted <=3 times then skipped, not looped forever.
#    architect sends one event; coder listens with an always-failing handler.
```

> Do NOT run commands needing a real token / remote server; the reviewer verifies the
> live poison simulation. Run only the SAFE checks (unit tests, --help).

## Rework vs. Escalate

- Rework locally only for deterministic failures (failing criterion, traceback, red tests,
  clear card violation).
- Escalate if a correct fix seems to require a server/protocol change (it should not), or an
  acceptance criterion is ambiguous.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Skip logic also skips events that would succeed on a later legitimate retry | Medium | Only count CONSECUTIVE failures; reset on any success; threshold >=3. |
| Accidentally ACKing/dropping a poison event a human needed to see | Medium | Prefer skip-without-ACK; document the choice; leave it inspectable. |
| Touching the SSE loop breaks reconnect/idle-exit/shutdown | Medium | Additive dict/set only; do not alter existing control flow branches. |

## Required Output Artifacts

- ImplementationReport (write to the path the dispatcher provides): what changed, the SAFE
  commands run and their output, and any deviation from this card.

---

## Planner Self-Check (completed before delegation)

- [x] Single concrete deliverable (poison-event skip after N attempts).
- [x] Scope / Out of Scope explicit; server-side dead-letter deferred.
- [x] Every acceptance criterion is command- or observation-verifiable.
- [x] Verification commands are the project's real commands.
- [x] Working Context has file+line anchors (process_event@411, failure paths, loop@478)
      so a fresh-session executor works from the card alone.
- [x] Advances a real Later-pool item found in dogfood; no unrelated refactors.
