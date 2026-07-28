# Implementation Report: SSE idle reconnect

## Changed

- Default daemon listeners use a 60-second read timeout and reconnect with the existing bounded
  backoff when the SSE stream stays silent.
- Explicit `--exit-after-idle` retains its existing one-shot idle exit behavior.
- Focused tests cover a timeout, reconnect, replayed delivered event, single handler invocation,
  successful ACK, and explicit idle exit.
- The changelog records the recovery behavior.

## Preserved

- Server APIs, SQLite state transitions, SSE frame format, payload display, handler argv, ACK,
  failed-attempt accounting, requeue, and authentication are unchanged.
- Reconnect recovery uses the existing at-least-once initial replay contract.
- No live event or historical payload was used by the automated tests.

## Verification

- Focused listener suite: 11 passed.
- Full isolated suite: 111 passed plus 10 subtests; one third-party warning.
- CI-equivalent Ruff selection (`E4,E7,E9,F`): passed.
- Ruff formatter for both changed Python files: passed.
- Python bytecode compilation and `git diff --check`: passed.
- Fresh Windows exact-head checkout: the two new reconnect tests passed; CI-equivalent Ruff,
  changed-file formatter, bytecode compilation, diff, SHA, and clean-tree gates passed.
- Windows full diagnostic: 96 tests passed, one skipped, and 10 subtests passed. Fourteen existing
  Windows-incompatible tests failed in the same setup/context, POSIX executable/quoting, Docker/Bash,
  listener diagnostic, SQLite cleanup, and poison-handler path areas already documented on the prior
  Agent Bus head; neither new reconnect test failed.

Pending final report-only SHA refresh on Windows, GitHub CI, independent Codex review, and main-agent
double-check.

## Known Baseline Noise

The unrestricted Ruff check retains pre-existing findings, and repository-wide format checking still
reports six pre-existing unformatted test files outside this TaskCard's allowed paths. Neither set was
changed here.
