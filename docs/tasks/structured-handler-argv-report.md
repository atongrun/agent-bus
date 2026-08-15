# P1-3 Structured Handler Argv Implementation Report

## Outcome

Agent Bus now accepts the pinned `agent-bus.listen.on-argv.v1` local consumer contract through
`listen --on-argv TYPE ARGV_JSON`. The JSON document is validated before any client connection,
rendered one existing argv token at a time, and passed to the unchanged
`subprocess.run(..., shell=False)` boundary. Legacy `--on TYPE COMMAND` remains available.

## Compatibility tuple

- Producer: `awf.handler-argv.v1`.
- Consumer: `agent-bus.listen.on-argv.v1`.
- Upgrade: Agent Bus, then Agent Workflow. Rollback: Agent Workflow, then Agent Bus.
- New Workflow plus old Bus fails during local Click argument parsing, before SSE connection or
  delivery. No event-time fallback or duplicate handler attempt is introduced.

## Scope and boundaries

- `client/cli.py` parses structured JSON, rejects invalid or duplicate registrations, renders
  placeholders without `shlex`, and reuses the existing handler execution and failure/ACK path.
- Focused tests cover paths with spaces, Unicode and metacharacters, invalid documents, pre-connect
  conflicts, and non-zero handler failure without ACK.
- The installed-client smoke exercises a disposable structured delivery on Windows and verifies the
  exact Unicode/metacharacter argument written by the child process.
- Server code, API/database schemas, authentication, SSE, delivery, ACK/fail/requeue transitions,
  PowerShell adapters, dependencies and deployment are unchanged. No retained business event or
  payload was read or operated.

## Local verification

The local Mac ran only `python3 -m compileall` for changed Python files, `git diff --check`, and
allowed-path/static inspection. Pytest, Ruff, installed-client acceptance and cross-platform proof
remain GitHub CI only.

## Remaining risk

The older `scripts/windows-poll-listener.ps1` remains an explicitly legacy bootstrap adapter with a
command template. The installed Python CLI is the supported cross-platform consumer for the pinned
Workflow tuple; removing the legacy script requires a separate deprecation package.
