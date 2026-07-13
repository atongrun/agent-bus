# Implementation Report — ABUS-INIT-DOCTOR-CROSSMACHINE-E2E-009

## Summary

Windows ACL lockdown for `agent-bus init` listener environment files. POSIX
retains `chmod(0o600)`; Windows calls `icacls` via argv with `shell=False` to
remove inherited ACEs and grant Full control to the current user only.

## Code changed

### `client/listener_config.py`

- **Added `_make_private(path)`** — platform dispatcher: POSIX → `chmod(0o600)`,
  Windows → `_make_private_windows()`.
- **Added `_make_private_windows(path)`** — resolves username via
  `USERNAME` / `USER` (fail-closed when neither is set), builds argv
  `["icacls", <path>, "/inheritance:r", "/grant:r", "<user>:F"]`, calls
  `subprocess.run(..., shell=False, text=True, errors="backslashreplace")`,
  and raises `OSError` on non-zero return or start failure.
- **`write_listener_env()`** — replaced `path.chmod(0o600)` calls with
  `_make_private()` on both the temporary and final file.

### `tests/test_listener_config.py`

- **`test_init_writes_private_file_and_never_prints_token`** — now decorated
  with `@patch("client.listener_config.subprocess.run")`. On POSIX asserts
  `stat.S_IMODE == 0o600`. On Windows asserts `mock_run.call_count == 2` and
  verifies icacls argv structure.
- **`test_windows_icacls_argv_is_correct`** — mocks `os.name="nt"` and
  `subprocess.run`, validates full icacls argv (path, inherit, grant,
  username:F), capture params, and timeout.
- **`test_windows_icacls_missing_username_raises`** — mocks
  `os.name="nt"` + empty `USERNAME`/`USER`, asserts `OSError` with
  "cannot determine Windows username".
- **`test_windows_icacls_nonzero_return_raises`** — mocks `os.name="nt"` and
  `subprocess.run` returning code 1, asserts `OSError` with "icacls
  returned 1".
- **`test_windows_icacls_start_failure_raises`** — mocks `os.name="nt"` and
  `subprocess.run` raising `OSError`, asserts `OSError` with "icacls
  failed to start".

## Automated test results

```text
Ran 14 tests in 0.037s

OK
```

All 14 tests pass on Windows (Git Bash + .venv/Scripts/python.exe). No
skipped permission assertions.

## Acceptance criteria results

| # | Criterion | Result |
|---|-----------|--------|
| 1 | POSIX writes still apply mode `0600` | ✅ Unchanged — `_make_private` calls `chmod(0o600)` on `os.name != "nt"` |
| 2 | Windows writes call `icacls` with correct argv, no shell | ✅ Verified by `test_windows_icacls_argv_is_correct` — argv = `[icacls, path, /inheritance:r, /grant:r, user:F]`, `shell=False` |
| 3 | Missing username / icacls start / non-zero → fail | ✅ Three focused tests cover all fail-closed paths |
| 4 | Focused tests pass without skipping permission | ✅ 4 new tests + platform-aware existing test, all pass, no skips |
| 5 | `init` succeeds with fixture + dummy token, no live credential | ✅ `AWF_CODER_TOKEN=dummy-not-a-live-token .venv/Scripts/agent-bus.exe init --force` → "Listener config written" (clean, no encoding errors) |
| 6 | Re-run without `--force` refuses to overwrite | ✅ `Error: Config already exists: ... Use --force to replace it.` |
| 7 | Generated file references token variable, contains no value | ✅ `AWF_CODER_TOKEN` referenced; `dummy-not-a-live-token` absent from file |
| 8 | `.awf/tmp/` removed before completion | ✅ `rm -rf .awf/tmp` executed |
| 9 | Reviewer live check (separate, not performed by executor) | ⏳ Deferred to reviewer — executor used only dummy token |
| 10 | ImplementationReport exists | ✅ This document |

## Commands executed (redacted)

```bash
# Automated test suite
.venv/Scripts/python.exe -m unittest tests.test_listener_config -v
# → Ran 14 tests ... OK

# Clean tmp before first run
rm -rf .awf/tmp

# First init (no --force needed because tmp was clean)
AWF_CODER_TOKEN=dummy-not-a-live-token .venv/Scripts/agent-bus.exe init \
  --agent coder --server-url http://127.0.0.1:8800 \
  --awf-env .awf/fixtures/init-doctor-awf-env.sh --repo-dir . \
  --script-dir scripts --config .awf/tmp/listener-e2e.env
# → Listener config written: .awf\tmp\listener-e2e.env
# → Load it with: source '.awf/tmp/listener-e2e.env'
# → Then run: agent-bus doctor --listener

# Re-run without --force → refuse
AWF_CODER_TOKEN=dummy-not-a-live-token .venv/Scripts/agent-bus.exe init \
  --agent coder --server-url http://127.0.0.1:8800 \
  --awf-env .awf/fixtures/init-doctor-awf-env.sh --repo-dir . \
  --script-dir scripts --config .awf/tmp/listener-e2e.env
# → Error: Config already exists: .awf\tmp\listener-e2e.env. Use --force to replace it.
# (exit 1 — correct refusal)

# Clean up generated artifacts
rm -rf .awf/tmp
```

## Deferred issues

- The intermittent Windows `0xC0000142` process-start failure was not
  encountered during this run. The UnicodeDecodeError from icacls non-UTF-8
  stderr was resolved via `errors="backslashreplace"` in `subprocess.run`.
  No other Windows poison-handler or DLL failures were observed.
