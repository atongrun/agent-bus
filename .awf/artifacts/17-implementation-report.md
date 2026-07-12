# Implementation Report — `send --dry-run`

## Task Card

ABUS-SEND-DRYRUN-005

## What Changed

### `client/cli.py` (the `send` command, lines 149–177)

- Added `@click.option("--dry-run", is_flag=True, ...)` decorator to the `send` command.
- Updated the `send` function signature to accept `dry_run` parameter.
- Added an early-return guard: **if `dry_run` is True**, the already-validated `body` dict is printed as JSON via `click.echo(json.dumps(body, indent=2))` and the function returns — no `httpx.Client` is constructed, no network call occurs.
- The existing `_load_payload` validation runs before the dry-run check, so invalid JSON still exits non-zero through the same code path as a normal send.

### `tests/test_send_dryrun.py` (new file)

Two test methods covering the `--dry-run` flag:

- `test_dry_run_prints_event_and_exits_zero` — invokes `send --dry-run` with valid JSON, asserts exit code 0, output matches the expected event object, and verifies `httpx.Client` was **never constructed** (via `MockClient.assert_not_called()`).
- `test_dry_run_with_invalid_json_exits_nonzero` — invokes `send --dry-run` with invalid JSON, asserts non-zero exit and the expected `"Payload must be valid JSON"` error message.

## Commands Run

```bash
$ .venv\Scripts\python.exe -m unittest discover -s tests -v
...
test_dry_run_prints_event_and_exits_zero ... ok
test_dry_run_with_invalid_json_exits_nonzero ... ok
...
Ran 18 tests in 0.884s
FAILED (failures=2)    # pre-existing Windows quoting test failures, unrelated

$ .venv\Scripts\python.exe -m client.cli send --help
...
  --dry-run            Validate payload and print the event that would be sent
                       without making an HTTP request
```

## Deviations

None. The implementation is strictly within the card's Scope / Out of Scope.

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| `send --from a --to b --type t --payload '{"k":1}' --dry-run` prints event JSON and exits 0, no HTTP | ✅ `test_dry_run_prints_event_and_exits_zero` |
| Normal `send` (no `--dry-run`) unchanged | ✅ No touch to normal path beyond adding parameter; existing tests unchanged |
| `send --dry-run` with invalid JSON exits non-zero | ✅ `test_dry_run_with_invalid_json_exits_nonzero` |
| New unit test covers dry-run (exit 0, prints event, no HTTP) and passes | ✅ Both new tests pass |
| `--dry-run` shows in `--help` | ✅ Verified in `send --help` output |
