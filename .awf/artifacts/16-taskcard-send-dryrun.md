# Task Card

## Task ID

ABUS-SEND-DRYRUN-005

## Background

`agent-bus send` builds an event and POSTs it to the server. There is no way to validate
the `--payload` JSON and preview the event *before* sending — an operator or a dispatcher
script (e.g. awf-dispatch) that wants to check "is this payload well-formed?" must either
send it for real or parse it separately. A `--dry-run` flag that validates the payload and
prints the event it *would* send, without any network call, closes that gap and matches the
roadmap's emphasis on boring, observable CLI diagnostics.

## Goal

Add a `--dry-run` flag to the `send` command that validates the payload JSON and prints the
event that would be sent (as JSON), then exits 0 WITHOUT making any HTTP request.

## Scope

- Add a `--dry-run` boolean flag to the `send` command in `client/cli.py`.
- When `--dry-run` is set: parse/validate the payload (reuse the SAME payload-loading the
  command already uses), print the resulting event object as JSON, and exit 0 — no HTTP call.
- When `--dry-run` is NOT set: behavior is completely unchanged.

## Out of Scope

- Do NOT change the server, the non-dry-run send path, or the payload-loading helper's logic.
- Do NOT add other flags.
- Do NOT change output of a normal (non-dry-run) send.

## Working Context (self-contained)

- **Repository / path**: this repo (`agent-bus`), current PR branch already checked out.
- **File to edit**: `client/cli.py` — the `send` command (search for `def send`). It already
  supports `--payload` and `--payload-file`, loaded via a helper (search for `_load_payload`).
  Reuse that helper for validation; do not reimplement JSON parsing.
- **Behavior to preserve**: a normal `send` still POSTs and prints the server response exactly
  as today. `--dry-run` must not import or require a live server.
- **Invalid payload**: if the payload JSON is invalid, `--dry-run` should fail the same way a
  normal send does today (the existing helper already raises/exits on bad JSON) — do not add
  new error handling, just let the existing validation run before the dry-run print.
- **Test style**: `tests/` uses `unittest` + `click.testing.CliRunner`. See
  `tests/test_pending.py` and `tests/test_cli_helpers.py`. For `--dry-run`, assert that the
  command exits 0 and prints the expected event JSON, and that NO HTTP client is constructed
  (you can patch `client.cli.httpx.Client` and assert it was not called).
- **Project rules**: see this project's `AGENTS.md`.

## Constraints

- `--dry-run` makes ZERO network calls (assert `httpx.Client` not used in the test).
- Exit 0 on success; on invalid payload, same non-zero exit as a normal send today.
- No new dependencies.

## Acceptance Criteria

- [ ] `agent-bus send --from a --to b --type t --payload '{"k":1}' --dry-run` prints the event
      JSON (including from/to/type/payload) and exits 0, making no HTTP request.
- [ ] A normal `send` (no `--dry-run`) is unchanged.
- [ ] `send --dry-run` with invalid JSON exits non-zero (existing validation).
- [ ] New unit test in `tests/` covers dry-run (exit 0, prints event, no HTTP client) and passes.
- [ ] Full suite passes: `.venv/bin/python -m pytest -q` (on the executing machine, run the
      project's normal test command).

## Verification Commands

```bash
# from the agent-bus repo root (use the machine's normal runner: .venv/bin/python or uv run):
.venv/bin/python -m pytest -q
.venv/bin/python -m client.cli send --help   # shows --dry-run
```

## Rework vs. Escalate

- **Rework locally** only for deterministic failures: a failed test/criterion or a clear card
  violation.
- **Escalate (stop and report)** if the goal is ambiguous, `_load_payload` is not found, or a
  change would exceed Out of Scope (e.g. you feel you must touch the server or the helper).

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Changing normal send output | Low | Gate all dry-run behavior behind `if dry_run:`, return before the HTTP call |
| Test needs a server | Low | Patch `httpx.Client`; dry-run must not construct it |

## Required Output Artifacts

- ImplementationReport at `.awf/artifacts/17-implementation-report.md`.

---

## Planner Self-Check

- [x] Goal is a single concrete deliverable (one `--dry-run` flag on `send`).
- [x] Scope / Out of Scope explicit and non-overlapping.
- [x] Every Acceptance Criterion is verifiable by a command or observable check.
- [x] Verification Commands are real (pytest runs on both Mac and Windows envs).
- [x] Working Context lets a fresh-session executor start without chat history (file, helper
      name, test style, mock guidance included).
- [x] Advances the current milestone (on-roadmap: CLI diagnostics / observability).
