# Review Report — ABUS-POISON-003 (executor: DeepSeek V4 Flash via awf-dispatch)

> Role: reviewer (Claude Code) | Date: 2026-07-11 | Method: constitution §7/§8.
> First task dispatched through `awf-dispatch.sh` (card-as-file, pointer event, local executor).

## Verdict: **PASS** — all safe + live acceptance criteria met; no rework needed.

## Reviewer verification (independent — not trusting the executor's self-report)

| Check | Result |
|-------|--------|
| Full unit suite (`unittest discover -s tests`) | ✅ 13 passed, OK (10 existing + 3 new) |
| `client/cli.py` parses (`ast.parse`) | ✅ syntax clean |
| `listen --help` shows `--max-event-attempts` (default 3) | ✅ (from executor log, re-derivable) |
| Diff scope | ✅ only `client/cli.py`, +48 lines, additive |
| **Live: poison event does not crash-loop** | ✅ real VPS: sent failing event, handler ran, event stayed un-ACKed, listener idle-exited (no infinite reprocess) |
| **Deterministic: handler stops after N attempts** | ✅ new regression test — 6 replays, cap 3 → handler runs exactly 3×, skip message printed |
| **Deterministic: skipped event not re-run on later replays** | ✅ new regression test — "previously skipped" on subsequent replays |
| **Deterministic: succeeding handler never falsely skipped** | ✅ new regression test |
| control:shutdown / --exit-after-idle / send / doctor / pending / ack | ✅ untouched |

## Code review (three poison-tracking paths, line-by-line)

1. **Handler template KeyError** (`cli.py:464-469`) — increments `failure_counts[event_id]`, skips at threshold. Correct.
2. **Handler non-zero exit** (`cli.py:472-476`) — `if not should_ack` after `run_handler`, increments, skips. Correct.
3. **JSON decode error in SSE loop** (`cli.py:527-536`) — uses `current_id` (the SSE `id:` field) since `event_data` didn't parse; guards `int()` with try/except. Correct scope + variable.
- **Success reset** (`cli.py:484`): `failure_counts.pop(event_id, None)` on ACK. Meets "consecutive failures reset on success."
- **Skip-without-ACK**: poison events remain un-ACKed and inspectable via `pending`/`ack`. Matches the card's preferred design.

## Executor behavior (weak-model, for the tiering record)

DeepSeek V4 Flash got architecture and requirements fully right and made all 8 additive edits. It **broke the try/except indentation once** (Edit 5), then re-read the file and fixed it in the next edit unprompted. No deterministic bug survived — cleaner than the ABUS-EXIT-002 run (which needed a bounded rework). Strong-review-as-safety-net still justified: the indentation slip would have been a syntax error had it not self-corrected.

## Real gap this review surfaced (NOT a blocker for this card — the impl matches the card)

**`failure_counts` is process-local closure state.** It accumulates only across SSE reconnects *within one listener process* (`cli.py:496` `while True`). The server replays un-ACKed events **only on connect** (`server/events.py:120`, Phase 1); Phase 3 only polls for *new* events. Therefore:

- The protection works for the original crash-loop (drop → reconnect → replay, same process).
- It does **NOT** persist across process restarts, and specifically **does nothing under `--once`** — which is exactly the mode `awf-dispatch` uses. A `--once` listener that hits a poison event exits after one attempt anyway, so no loop; but a restart-on-crash supervisor would re-run the poison event fresh each time with a zeroed counter.

**Proper fix belongs server-side**: mark repeatedly-failing events `status='failed'` (the DB enum already exists, `server/db.py:52`) so replay stops for *all* listeners. Recorded to Later (dead-letter) in `ai-memory/.../2026-07-11-agent-bus-dogfood-findings.md` #1. The client-side cap shipped here is correct first-aid and satisfies the card.

## Recommendation

**Approve.** The card's goal (no crash-loop; stop after N; reset on success; no regression) is met and now covered by deterministic regression tests. Next decisions for the operator:
1. Commit the working-tree changes (`client/cli.py`, `.awf/artifacts/12`, `.awf/artifacts/13`, `tests/test_poison_event.py`) on `awf/abus-poison-003`.
2. Whether to also open the server-side dead-letter Later item now or defer (use-first: defer until a real multi-listener/supervisor setup needs it).
