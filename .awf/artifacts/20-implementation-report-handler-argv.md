# Implementation Report

## Task

Three-OS root-cause fix (research step 3): run handlers as an argv list with
`shell=False`, eliminating the triple-parse (awf builds argv → serialized to
string → cmd.exe/sh re-parses) that made Windows handler spawning unreliable.

Branch: `awf/abus-handler-argv-007` (forked from `awf/abus-bootstrap-token-006`
@`94e972e`). Companion change lives in agent-workflow (`awf_role.py` / `awf_listen.py`).

## Changes

| File | Change |
|------|--------|
| `client/cli.py` | `render_command` now returns an **argv list** (`list[str]`) instead of a shell string. It `shlex.split(template, posix=True)` once, then substitutes each standalone `{placeholder}` token as a single raw argv element (no shell-quoting, no re-split). `run_handler` takes an argv list and runs `subprocess.run(argv, shell=False, ...)`. Deleted `_quote_command_value` and its `list2cmdline`/`shlex.quote` branching. |
| `tests/test_cli_helpers.py` | Rewrote the two render tests to assert argv lists; added coverage for a space-containing value (one element), shell metacharacters (passed verbatim), and a double-quoted path with spaces (one token). Updated the run_handler test to pass an argv list. |

## Why

Previously each `{payload.*}` value was shell-quoted and spliced into one string
that was later re-parsed by `shell=True` (cmd.exe on Windows). Three parses across
two shell dialects → WSL bash shadowing git-bash, spaces in the git-bash path,
single-quote handling, gbk crashes. Running a real argv with `shell=False` removes
the shell entirely: one parse, no dialect, and shell metacharacters in payload
values are inert (no injection surface).

## Test Results (macOS)

```
16 passed in 0.19s   (.venv/bin/python -m pytest tests/ -q)
```

- No regressions: all pre-existing tests (auth, bootstrap-token, events, cli) pass.
- The two previously Windows-only failing tests in `test_cli_helpers.py` (they
  asserted `list2cmdline` quoting) are gone — the quoting they tested no longer exists.

## Integration + cross-machine verification

- **Integration (macOS)**: fed the handler that agent-workflow `awf_listen.build_handler()`
  produces (with a git-bash python exe path containing a space) through this
  `render_command`. Result: the exe and script paths are each a single argv element;
  a card path with a space is one element; `note; echo pwned` is passed verbatim; an
  empty `--model` value stays a distinct empty element. PASS.
- **Windows (real machine, over Tailscale; `tailscale status` confirmed online)**:
  `shlex.split → argv → shell=False` runs a real git command rc=0, keeping the
  space-containing git-bash exe/script paths as single tokens. Note: the original
  intermittent `0xC0000142`/rc≠0 could not be reproduced on demand (the box is not
  currently in the broken state — the bug was never deterministically pinned). This
  fix is structural: it removes the shell-reparse layer where the nondeterminism lived
  rather than patching a specific symptom.

## Deviations

None from the agreed approach (keep `--on TYPE COMMAND` string interface, split to
argv internally). Service definitions + justfile (research steps 4–5) are a separate,
later task.

## Status

Committed locally on `awf/abus-handler-argv-007` (`0290ec8`). **Not pushed, not merged**
— awaiting user decision (stacks on the reviewed but unmerged bootstrap-token branch).
