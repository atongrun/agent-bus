# TaskCard: P1-3 Structured Handler Argv Transport

## Task ID

ABUS-USABILITY-P1-3

## Objective

Add a versioned, structured handler-argv input to the local Agent Bus listener so runtimes can pass
an exact JSON array without command-string parsing. Preserve the transport protocol, server state,
handler-success ACK rule, durable failure accounting, and current command-template compatibility.

## Frozen compatibility tuple

- Producer contract: `awf.handler-argv.v1`.
- Consumer contract: `agent-bus.listen.on-argv.v1`.
- Upgrade order: Agent Bus first, then Agent Workflow. Rollback order: Agent Workflow first, then
  Agent Bus.
- New Agent Bus accepts both `--on-argv TYPE ARGV_JSON` and legacy `--on TYPE COMMAND`. New Agent
  Workflow requires `--on-argv`; an old Bus therefore fails during local CLI argument parsing,
  before an SSE connection or event delivery, rather than silently falling back.

## Base and branch

- Repository: `atongrun/agent-bus`
- Base: `master@6b3955d172d1d1709998af3b93205a40f2803b3a`
- Branch: `codex/structured-handler-argv`
- Cross-repository peer base: Agent Workflow
  `main@3ba544c2e2d0c58c94e7364bc28e3b7ad1c358d2`

## Allowed changes

1. `docs/tasks/structured-handler-argv.md`
2. `docs/tasks/structured-handler-argv-report.md`
3. `client/cli.py`
4. `tests/test_cli_helpers.py`
5. `tests/test_poison_event.py`
6. `scripts/test-client-setup.py`
7. `README.md`
8. `CHANGELOG.md`
9. `docs/guide/installation.md`
10. `docs/roadmap.md`
11. `HANDOFF.md`

Do not modify server code, database/API schemas, authentication, SSE delivery, ACK/fail/requeue
transitions, dependencies, deployment scripts, or Workflow files.

## Required behavior

- `--on-argv TYPE ARGV_JSON` accepts one non-empty JSON array whose elements are strings. It rejects
  malformed JSON, non-arrays, empty arrays, non-string elements, and duplicate/conflicting handler
  registrations before connecting to Agent Bus.
- Each structured argv element is a template token. Placeholder values replace data inside that
  token without `shlex`, `cmd.exe`, PowerShell, or POSIX-shell parsing. A standalone placeholder is
  one exact argv element even when it contains spaces, Unicode, quotes, or metacharacters.
- The rendered list reaches the existing `subprocess.run(..., shell=False)` boundary unchanged.
- Legacy `--on TYPE COMMAND` retains its current one-time `shlex` compatibility behavior and is
  documented as a compatibility surface, not the preferred runtime contract.
- Handler exit zero remains the only handler-driven ACK path. Missing fields, parse failure,
  start failure, timeout, and non-zero exit retain the existing unacknowledged/durable-failure path.
- No handler configuration is stored in the server, event payload, context, or database. Agent Bus
  remains transport-only and does not learn Workflow stages, Git, models, recovery, or routing.

## Verification level

**Level B; two focused tests plus the existing installed-client smoke.**

- A table-driven helper test covers executable/script paths with spaces, Unicode, and a
  representative metacharacter, plus invalid structured documents and unchanged legacy parsing.
- A listener failure test proves a structured handler non-zero records failure and never ACKs.
- The installed-client smoke on Windows confirms the published CLI exposes and renders the v1
  structured contract. Existing Linux CI covers the full suite and static gates; Agent Workflow's
  peer CI supplies macOS installed-wheel coverage for the pinned tuple.

Local Mac verification is limited to compile/static/diff checks. Pytest and Ruff run only in
GitHub CI.

## Stop conditions

- Stop if implementation requires reading or mutating any retained event or business payload.
- Stop if server protocol/state or handler-success ACK semantics must change.
- Stop if structured values can be reinterpreted by a shell or if compatibility needs an implicit
  retry that could receive the same event under two handler modes.

## Required output

Minimal code/tests, implementation report, Lore commits, independent PR, green CI, exact-head
independent review, fresh mergeability, merge, post-merge master/CI proof, pinned peer tuple, and
short-branch cleanup.
