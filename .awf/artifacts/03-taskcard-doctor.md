# Task Card

## Task ID

ABUS-DOCTOR-001

## Background

Real end-to-end use of Agent Bus (over the user's VPS, driving local OpenCode) worked, but
every setup/troubleshooting step was manual SSH + curl — the operator could not tell where
config/token lived or whether the queue was healthy without probing. The project's own
`docs/recommended-practices.md:36-48` ranks a `doctor` command as the single most important
near-term improvement. Architecture is frozen for this milestone (see
`.awf/artifacts/02-architecture-decision.md`, D1–D5).

## Goal

Add a new `agent-bus doctor` CLI subcommand that self-checks a client's configuration and
connectivity and prints actionable PASS/FAIL results, so a user can diagnose setup without
manual probing.

## Scope

- Add one new `doctor` subcommand to `client/cli.py`.
- Checks, in order: (1) config present (URL / token / agent name), (2) server `/health`
  reachable, (3) auth scope valid — can list own pending events.
- Optional `--send-test` flag: additionally do a real send → pending → ack round-trip to
  the agent itself, then clean up the test event.

## Out of Scope

- No changes to `server/`, the DB schema, the wire protocol, or any existing command.
- No new Python dependencies.
- Do NOT implement P2 (work-queue lease), P3 (exit mechanism), or P4 (TTL). Those are Later.
- No cross-machine / instance-addressing logic.

## Working Context (self-contained)

- **Repository / path**: `<agent-bus-repo>`
- **File to edit**: `client/cli.py` (single file; the CLI lives entirely here).
- **How commands are registered**: Click group `cli` at `client/cli.py:128`. Add the new
  command with the `@cli.command()` decorator (see `send` at `:141`, `pending` at `:189`).
- **Config access**: two ways already exist —
  - `get_config()` at `client/cli.py:21` returns `(url, token, agent)` from env
    `AGENT_BUS_URL` / `AGENT_BUS_TOKEN` / `AGENT_BUS_AGENT`.
  - the Click context: `ctx.obj["url"]`, `ctx.obj["token"]` (set at `:136-138`). Use
    `@click.pass_context` and, for the agent name, add `--agent` with
    `envvar="AGENT_BUS_AGENT"` like `pending` does at `:190`.
- **HTTP style**: use `httpx.Client(timeout=10)` and `get_headers(token)` (`:29`), matching
  `send` (`:161-177`). Print with `click.echo(...)`; errors to stderr with `err=True`;
  fail with `sys.exit(1)` (matches `send`).
- **Endpoints to call** (all already implemented in `server/events.py`):
  - `GET  {url}/health` → `{"status":"ok",...}` (no auth).
  - `GET  {url}/events/pending?agent=<agent>` with `Authorization: Bearer <token>` →
    `200` + JSON array if token is valid for that agent; `403` if token/agent mismatch.
  - For `--send-test` only: `POST {url}/events` (body `from_agent,to_agent,type,payload`),
    then `POST {url}/events/{id}/ack?agent=<agent>`.
- **Relevant existing behavior that must not regress**: `send`, `listen`, `pending`, `ack`
  keep working unchanged. Unit tests in `tests/` keep passing.
- **Project rules**: see `AGENTS.md` if present; otherwise follow this file's own style
  (4-space indent, Click decorators, `httpx`, `click.echo`).

## Constraints

- Additive only (decision D1): no server / DB / protocol / existing-command changes.
- Default `doctor` is **read-only** and creates **no events** (decision D2). Only
  `--send-test` writes an event, and it must ACK/clean it up afterward.
- Each check prints PASS/FAIL and, on failure, the concrete fix (which env var or command)
  (decision D3).
- Exit code 0 iff all non-optional checks pass; non-zero otherwise (decision D4).
- No new dependencies (decision D5).

## Acceptance Criteria

- [ ] `agent-bus doctor --help` shows the new command.
- [ ] With a reachable server + valid coder token/agent, `agent-bus doctor` prints PASS for
      config, health, and auth-scope checks and exits 0.
- [ ] With a wrong/empty token, the auth-scope check prints FAIL with a hint and the command
      exits non-zero (does not crash/traceback).
- [ ] With an unreachable URL, the health check prints FAIL with a hint and exits non-zero.
- [ ] `agent-bus doctor --send-test` (valid config) completes a send→pending→ack round-trip,
      reports PASS, and leaves the queue clean (no leftover test event).
- [ ] Existing unit tests still pass: `.venv/bin/python -m unittest discover -s tests` → OK.
- [ ] `send` / `listen` / `pending` / `ack` remain unchanged in behavior.

## Verification Commands

```bash
cd <agent-bus-repo>

# 1) existing tests still green
.venv/bin/python -m unittest discover -s tests

# 2) help shows the new command
.venv/bin/agent-bus doctor --help

# 3) happy path against the user's VPS as coder (read-only, creates no events)
AGENT_BUS_URL=$AGENT_BUS_URL \
AGENT_BUS_TOKEN=<coder-token> AGENT_BUS_AGENT=coder \
  .venv/bin/agent-bus doctor ; echo "exit=$?"

# 4) failure path: bad token -> auth FAIL, non-zero exit
AGENT_BUS_URL=$AGENT_BUS_URL \
AGENT_BUS_TOKEN=wrong AGENT_BUS_AGENT=coder \
  .venv/bin/agent-bus doctor ; echo "exit=$?"

# 5) failure path: unreachable server -> health FAIL, non-zero exit
AGENT_BUS_URL=http://127.0.0.1:1 \
AGENT_BUS_TOKEN=x AGENT_BUS_AGENT=coder \
  .venv/bin/agent-bus doctor ; echo "exit=$?"

# 6) opt-in round-trip self-test, leaves queue clean
AGENT_BUS_URL=$AGENT_BUS_URL \
AGENT_BUS_TOKEN=<coder-token> AGENT_BUS_AGENT=coder \
  .venv/bin/agent-bus doctor --send-test ; echo "exit=$?"
```

> The executor should ask the operator for `<coder-token>` (a secret) rather than hardcode
> it, or read it from the environment/.env already present on this machine.

## Rework vs. Escalate

- **Rework locally** only for deterministic failures: a failing acceptance criterion, a
  traceback, tests going red, or a clear violation of this card.
- **Escalate (stop and report)** if: the task needs a server/protocol/DB change to work
  (would violate Out of Scope), config/token is unavailable, or an acceptance criterion is
  ambiguous.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `--send-test` leaves a test event un-ACKed, clogging the real queue | Medium | ACK/clean the test event in a `finally`; use a distinct `type` like `control:doctor-test`. |
| Hardcoding a secret token into code/history | Medium | Read token from env/.env or prompt; never write it into `cli.py`. |
| Touching shared helpers breaks `send`/`pending` | Low | Add a self-contained command; reuse `get_config`/`get_headers` read-only. |

## Required Output Artifacts

- ImplementationReport: what changed in `client/cli.py`, the exact verification commands run,
  their output (PASS/FAIL + exit codes), and any deviation from this card.

---

## Planner Self-Check (completed before delegation)

- [x] Goal is a single concrete deliverable (one `doctor` subcommand).
- [x] Scope and Out of Scope are explicit and non-overlapping.
- [x] Every acceptance criterion is verifiable by a command or observable check.
- [x] Verification commands are the project's real commands (`.venv/bin/agent-bus`,
      `unittest discover -s tests`) — confirmed against the codebase.
- [x] Working Context lets a fresh-session executor start without this chat history
      (file path, exact line-number anchors, endpoints, style all inline).
- [x] Advances the current milestone (M1 = doctor); no unrelated refactors.
