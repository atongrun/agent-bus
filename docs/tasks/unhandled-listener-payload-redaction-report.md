# Implementation Report: Unmatched listener payload redaction

## Changed

- Handler-driven listeners decide whether an event type has a matching handler before reading its
  payload for display.
- Events without a matching handler show safe metadata, omit `payload.task_id`, and replace the raw
  payload with a stable redaction marker.
- Regression coverage preserves manual listener and explicit `--ack-on-receive` behavior.
- The changelog documents the safer handler-driven display behavior.

## Preserved

- Matching handlers retain the existing payload display and execution behavior.
- Manual listeners without handlers retain raw payload display behavior.
- Explicit `--ack-on-receive` retains raw payload display and ACK behavior.
- Unmatched events remain unacknowledged and do not enter failure accounting.
- Server APIs, storage, delivery, retry, requeue, and authentication are unchanged.

## Verification

- Regression lock before implementation: 1 expected failure, 8 passes.
- Focused listener suite after implementation: 9 passes.
- Full isolated pytest suite: 109 passes plus 10 subtests; one third-party deprecation warning.
- CI-equivalent Ruff selection (`E4,E7,E9,F`): passes across client, server, tests, and the client
  setup script.
- Ruff formatter: both changed Python files pass. The broader repository formatter command still
  reports six pre-existing unformatted test files outside this TaskCard's allowed paths.
- Python bytecode compilation: passes across client, server, and tests.
- Git whitespace validation: passes.
- Fresh Windows exact-head checkout: the three new unmatched-payload acceptance tests pass; the CI
  Ruff selection, changed-file formatter, and bytecode compilation pass; tracked files remain clean.
- Windows full diagnostic: 94 tests pass, one skips, and 10 subtests pass. Fourteen pre-existing
  Windows-incompatible tests fail around POSIX handler quoting, XDG-only test setup, executable-bit
  assertions, Bash availability, and SQLite temporary-file locking; none touches the new redaction
  branch. The same run includes all three passing redaction acceptance tests.

Pending GitHub CI, independent Codex review, and main-agent double-check.

## Not verified

- Live historical event state was intentionally not queried during implementation; non-mutation is
  covered by isolated ACK/fail mocks and will be checked only through a safe post-rollout probe.
