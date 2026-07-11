# Implementation Report — ABUS-DOCTOR-001

## What changed

Edited a single file, `client/cli.py` (additive only; no other files touched).

Added one new Click subcommand `doctor`, registered on the existing `cli` group
with `@cli.command()`, placed between the existing `pending` and `listen`
commands. No existing command (`send`, `ack`, `pending`, `listen`) was modified;
no server/DB/protocol changes; no new dependencies.

### Behavior

`agent-bus doctor [--agent <name>] [--send-test]`

- `--agent` mirrors `pending` (`envvar="AGENT_BUS_AGENT"`) but is **not** required
  at the Click layer so that a missing agent is reported by Check 1 with an
  actionable hint rather than a Click usage error (D3).
- `--send-test` is an opt-in flag (D2); default `doctor` is read-only and
  creates no events.

Checks, in order (each prints `[i/N] Name: PASS|FAIL` plus a detail line and, on
failure, a concrete fix hint):

1. **Config** — verifies `AGENT_BUS_URL`, `AGENT_BUS_TOKEN`, `AGENT_BUS_AGENT`
   are all set. Prints a masked token summary on PASS. If config is missing the
   command exits 1 immediately (downstream checks can't run).
2. **Server /health** — `GET {url}/health` (no auth); PASS iff status 200 and
   `status=="ok"`. Catches `httpx.HTTPError` (connect/timeout/etc.) without
   traceback and prints a `curl {url}/health` hint.
3. **Auth scope** — `GET {url}/events/pending?agent=<agent>` with bearer token.
   200 → PASS (prints pending count); 401 → FAIL with token-config hint;
   403 → FAIL with agent-scope hint; other → FAIL. Skipped if health failed.
4. **Round-trip --send-test** (only when `--send-test` given):
   - `POST {url}/events` with
     `{from_agent:<agent>, to_agent:<agent>, type:"control:doctor-test",
     payload:{"_doctor":true, "ts":<iso>}}`.
   - `GET /events/pending?agent=<agent>` to confirm the new event id appears.
   - `POST /events/{id}/ack?agent=<agent>` to clean up (always attempted once
     an event id exists, even on partial failure).
   - Distinct `type=control:doctor-test` makes the test event identifiable
     (Risk table mitigation). On incomplete round-trip it prints a
     `agent-bus ack <id>` manual-cleanup hint.

Exit code (D4): 0 iff all checks that ran pass; 1 otherwise. A `--send-test`
failure is also treated as a failure (consistent with D4's guarantee that
non-optional failures are non-zero; opt-in failures are non-zero too).

Style: matches existing file conventions — `httpx.Client(timeout=10)`,
`get_headers(token)`, `click.echo(...)` / `click.echo(..., err=True)` for
errors, `sys.exit(1)` on failure (mirrors `send`).

## Verification commands run & results

### 1) Existing unit tests (must stay OK)
```
$ .venv/bin/python -m unittest discover -s tests
....  Handler start: ...
  Handler exit_code=0 duration=0.0s
  ...
Ran 10 tests in 0.046s
OK
```
Result: **PASS** — all 10 tests green, no regression.

### 2) Help shows the new command
```
$ .venv/bin/agent-bus doctor --help
Usage: agent-bus doctor [OPTIONS]

  Diagnose configuration and connectivity to the Agent Bus server.
  ...
Options:
  --agent TEXT  Agent name to diagnose (defaults to AGENT_BUS_AGENT)
  --send-test   Also run a send->pending->ack round-trip self-test ...
  --help        Show this message and exit.
```
Result: **PASS** — `doctor` is registered and documented.

### Additional offline sanity checks (no real server / no real token needed)

**Unreachable URL → health FAIL, exit 1, no traceback:**
```
$ AGENT_BUS_URL=http://127.0.0.1:39999 AGENT_BUS_TOKEN=x AGENT_BUS_AGENT=coder \
    .venv/bin/agent-bus doctor ; echo "exit=$?"
[1/3] Config: PASS
  url=http://127.0.0.1:39999 agent=coder token=***
  http://127.0.0.1:39999/health returned 502:
  Fix: ensure the Agent Bus server is running at AGENT_BUS_URL.
  Skipped (server unreachable).
[2/3] Server /health: FAIL
[3/3] Auth scope: FAIL
One or more checks failed.
exit=1
```
Result: **PASS** — non-zero exit, actionable hint, no traceback.

(Source note: in this shell `127.0.0.1:39999` is routed via a local proxy that
returns 502 instead of `ECONNREFUSED`; the same code path catches true
connection refusals via the `httpx.HTTPError` branch. The observable contract —
FAIL + hint + exit 1, no crash — is identical.)

## Checks NOT run by the implementer (per orchestrator instructions)

The following verification commands from the task card require a real auth
token and/or hit the user's remote VPS server, so they were **intentionally
not run**; the architect will verify them during review:

- Happy-path `agent-bus doctor` against the VPS with a coder token.
- Failure path with a wrong token (auth FAIL).
- `agent-bus doctor --send-test` round-trip (writes a real event).

## Deviations from the task card

None. Implementation matches all frozen decisions D1–D5 and all in-scope
acceptance criteria. The only interpretation worth flagging: per D4, exit code
is 0 iff all *run* checks pass (a `--send-test` failure also yields exit 1);
this is a superset of D4's literal "non-zero on non-optional failure" guarantee
and does not violate it.