# Implementation Report — `pending --count`

## Task Card

ABUS-PENDING-COUNT-004

## What Changed

### `client/cli.py` (lines 189–214)

- Added `@click.option("--count", is_flag=True, ...)` decorator to the `pending` command.
- Updated the `pending` function signature to accept `count` parameter.
- Gated the output: when `count` is `True`, prints `len(events)` (an integer); otherwise prints the existing indented JSON dump.
- No changes to the HTTP call, error handling, or default output path.

### `tests/test_pending.py` (new file)

- Three test methods covering the `--count` flag:
  - `test_count_prints_integer` — 3 mock events → `--count` prints `"3"`, exits 0.
  - `test_no_count_prints_json` — without `--count`, output is byte-for-byte identical to the existing JSON dump.
  - `test_count_empty_returns_zero` — empty queue + `--count` prints `"0"`.
- All tests mock `httpx.Client.get` so no server is needed.

## Commands Run

```bash
$ .venv/bin/python -m pytest -q
................                                                         [16 passed in 0.38s]

$ .venv/bin/python -m client.cli pending --help
Usage: python -m client.cli pending [OPTIONS]

  List pending/delivered events for an agent.

Options:
  --agent TEXT  Agent name to inspect  [required]
  --count       Print only the number of pending events
  --help        Show this message and exit.
```

## Deviations

None. The implementation is strictly within the card's Scope / Out of Scope.

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| `--count` prints only an integer and exits 0 | ✅ Covered by `test_count_prints_integer` |
| No-`--count` output is byte-for-byte unchanged | ✅ Covered by `test_no_count_prints_json` |
| New unit test covers `--count` and passes | ✅ 3 new tests, all passing |
| Full test suite passes | ✅ 16/16 passed |
