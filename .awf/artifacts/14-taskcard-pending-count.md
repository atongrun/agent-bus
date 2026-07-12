# Task Card

## Task ID

ABUS-PENDING-COUNT-004

## Background

The v0.x roadmap (`docs/roadmap.md`) calls for improving pending / un-ACKed
inspection, and its acceptance criteria include proving `send -> pending -> ... -> ACK
-> pending empty`. Today `agent-bus pending --agent X` prints the full JSON array of
events, so a script that only wants to check "is this agent's queue empty?" must parse
JSON. A dispatcher's pre-flight check ("confirm the coder queue is clean before sending")
would be simpler and more robust with a machine-friendly count.

## Goal

Add a `--count` flag to the `pending` command that prints ONLY the integer number of
pending events for the agent (one line, no JSON) and exits 0.

## Scope

- Add a `--count` boolean flag to the `pending` command in `client/cli.py`.
- When `--count` is set, print just the number of events (e.g. `3`) and exit 0.
- When `--count` is NOT set, behavior is unchanged (existing indented JSON output).

## Out of Scope

- Do NOT change the `/events/pending` server endpoint or its response shape.
- Do NOT change the default (non-`--count`) output.
- Do NOT add other flags (`--json`, `--quiet`, filtering, etc.).
- Do NOT touch delivery/ACK/listen logic.

## Working Context (self-contained)

- **Repository / path**: this repo (`agent-bus`). The card is on the current PR branch;
  the code you edit is already checked out.
- **File to edit**: `client/cli.py` — the `pending` command is defined at lines ~189–211:

  ```python
  @cli.command()
  @click.option("--agent", envvar="AGENT_BUS_AGENT",
                required=True, help="Agent name to inspect")
  @click.pass_context
  def pending(ctx, agent):
      """List pending/delivered events for an agent."""
      ...
      events = resp.json()
      click.echo(json.dumps(events, indent=2, ensure_ascii=False))
  ```

  `events` is a Python list (the endpoint returns a JSON array). `json` is already
  imported at the top of the file. Add the flag and, when set, `click.echo(len(events))`
  instead of the JSON dump.
- **Relevant existing behavior that must not regress**: without `--count`, the command
  must still print the same indented JSON it prints today.
- **Test style**: tests live in `tests/`, use `unittest` + `click.testing.CliRunner`.
  See `tests/test_cli_helpers.py` for how CLI commands are invoked in tests. Mock the
  HTTP call (the command uses `httpx.Client(...).get(...)`) so the test needs no server.
- **Project rules**: see this project's `AGENTS.md` for stack and conventions.

## Constraints

- `--count` prints exactly the integer and a trailing newline — nothing else on stdout.
- Exit code 0 on success (same as today).
- No new dependencies.

## Acceptance Criteria

- [ ] `agent-bus pending --agent X --count` prints only an integer (the number of pending
      events) and exits 0.
- [ ] `agent-bus pending --agent X` (no `--count`) output is byte-for-byte unchanged.
- [ ] A new unit test in `tests/` covers `--count` (asserts the integer output for a
      mocked list of N events) and passes.
- [ ] Full test suite passes: `.venv/bin/python -m pytest -q`.

## Verification Commands

```bash
# from the agent-bus repo root:
.venv/bin/python -m pytest -q
# sanity-check the help shows the new flag:
.venv/bin/python -m client.cli pending --help
```

## Rework vs. Escalate

- **Rework locally** only for deterministic failures: a failed test, a failed acceptance
  criterion, or a clear violation of this card.
- **Escalate (stop and report)** if the goal is ambiguous, required context is missing,
  or a change would exceed **Out of Scope** (e.g. you feel the need to change the server).

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Accidentally changing default output | Low | Keep the JSON branch untouched; gate `len()` behind `if count:` |
| Test needs a live server | Low | Mock `httpx.Client.get` in the test, as existing tests do |

## Required Output Artifacts

- ImplementationReport at `.awf/artifacts/15-implementation-report.md` (what changed,
  commands run + results, any deviation).

---

## Planner Self-Check

- [x] Goal is a single concrete deliverable (one `--count` flag).
- [x] Scope and Out of Scope are explicit and non-overlapping.
- [x] Every Acceptance Criterion is verifiable by a command or observable check.
- [x] Verification Commands are real (`.venv/bin/python -m pytest -q` runs; 13 tests pass today).
- [x] Working Context lets a fresh-session executor start without chat history (file, line
      range, current code, test style, mock guidance all included).
- [x] This task advances the current milestone (on-roadmap: pending inspection).
