# Review Report — ABUS-EXIT-002 (executor: DeepSeek V4 Flash)

> Role: reviewer (Claude Code) | Date: 2026-07-11 | Method: constitution §7/§8.

## Verdict: **REQUEST_CHANGES** (one deterministic bug; one feature works perfectly)

## Reviewer verification (real, against VPS)

| Check | Result |
|-------|--------|
| Existing unit tests | ✅ 10 passed, OK |
| `listen --help` shows `--exit-after-idle` | ✅ |
| **idle-exit** (`--exit-after-idle 5`) | ❌ **crashes with ValueError** — feature unusable |
| **control:shutdown** remote exit (Hermes role sends event) | ✅ listener printed msg, ACKed, exited 0 in ~2s |
| target-mismatch ignore logic (code review) | ✅ correct (`target != agent → ignore`) |
| shutdown event ACK'd (queue clean after) | ✅ pending = `[]` |
| Diff scope | ✅ only `client/cli.py`, +27 lines, additive |

## Deterministic failure (must rework — constitution §7)

**`--exit-after-idle` crashes on use.** `client/cli.py:398`:
```python
timeout_config = httpx.Timeout(connect=30.0, read=float(exit_after_idle)) if exit_after_idle else None
```
raises `ValueError: httpx.Timeout must either include a default, or set all four parameters
explicitly.` httpx requires either a `timeout=<default>` or all of connect/read/write/pool.
Only `connect` and `read` were given → the command fails immediately with a traceback.

**Fix (small):** provide all four, e.g.
`httpx.Timeout(float(exit_after_idle), connect=30.0)` (positional = default for the
unset ones), or set write/pool explicitly. Then re-verify the idle-exit acceptance criterion
against the VPS (does the SSE `read` timeout actually fire when the server sends nothing?
This still needs a real-server check after the crash is fixed).

## What works (no rework needed)

- **control:shutdown** — the operator's key Hermes scenario — works end to end: ACK + exit 0.
- **target** name-match logic is correct and correctly scoped to `control:shutdown` only.
- ACK-before-exit constraint honored (shutdown event does not replay).
- Additive-only, no server/protocol change, no new deps, tests green.

## Advisory (non-blocking)

- After the fix, idle-exit's real behavior against a keep-alive SSE stream still needs a live
  check (open question flagged in the card's risk table). If the server streams periodic
  data, the `read` timeout may never fire — may need an app-level idle timer instead.

## Recommendation

Request one bounded rework: fix the `httpx.Timeout` construction and re-verify idle-exit on
the VPS. Everything else is approved.

---

## Rework verification (2026-07-11, after DeepSeek Flash bounded rework)

The one deterministic bug was reworked by the same executor (DeepSeek V4 Flash) in one pass
(~30s) after reading this review.

- Fix applied at `client/cli.py:398`: `httpx.Timeout(float(exit_after_idle), connect=30.0)`
  (exactly the suggested fix — idle value as default, connect stays 30s).
- Reviewer re-verified against the VPS:
  - `--exit-after-idle 5` → connects, waits, prints "No events received for 5s; exiting.",
    exits cleanly (no ValueError, no traceback). ~5s + connect overhead. ✅
  - Open question resolved: the SSE `read` timeout DOES fire on this server (idle detection
    works in practice), so no app-level timer was needed. ✅
  - Existing unit tests still pass (10 OK). ✅
- control:shutdown (verified earlier) unaffected. ✅

## Updated verdict: **PASS** — all acceptance criteria met after one bounded rework.

## Rework-loop finding (workflow process, for Later)

The first rework dispatch crash-looped the listener because the orchestrator's handler prompt
contained a non-ASCII em-dash that corrupted the SSE event ('utf-8' surrogate error). Root
cause was the dispatch method (inline prompt through shell), NOT the executor. Two takeaways:
(1) Agent Bus should protect against poison events (a bad/failing event should not infinitely
re-deliver and crash-loop the listener) — recorded to Later.
(2) Dispatch should pass the prompt via a file, never inline — motivates the `awf-dispatch`
helper.
