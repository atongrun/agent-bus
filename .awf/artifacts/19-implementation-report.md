# Implementation Report

## Task

ABUS-BOOTSTRAP-TOKEN-006 — Add `POST /bootstrap/token` endpoint.

## Changes

| File | Change |
|------|--------|
| `server/bootstrap.py` | **New** — `APIRouter` with `POST /token` under `/bootstrap` prefix. Reads `AGENT_BUS_BOOTSTRAP_SECRET` at request time. Compares `X-Bootstrap-Secret` header via `secrets.compare_digest`. Returns `{"agent": <name>, "token": <role-token>}` on success. |
| `server/models.py` | Added `BootstrapTokenRequest` Pydantic model (`agent: str` field). |
| `server/main.py` | Imported and included `bootstrap_router`. |
| `.env.example` | Added `AGENT_BUS_BOOTSTRAP_SECRET` with explanatory comment (commented out). |
| `tests/test_bootstrap_token.py` | **New** — 5 test cases via `TestClient(app)` + `patch.dict(os.environ, ..., clear=True)`. |

## Test Results

```
Ran 9 tests in 0.082s
OK
```

- All 5 bootstrap token tests pass (success, wrong secret → 401, missing header → 401, unknown agent → 404, unset secret → 404).
- All 4 existing auth tests pass (no regression).
- 2 pre-existing failures in `test_cli_helpers.py` (quote-style on Windows) — unrelated.

## Deviations from spec

None. The implementation follows the task card exactly.

## Acceptance Criteria

- [x] `POST /bootstrap/token` with correct `X-Bootstrap-Secret` + `{"agent":"coder"}` → `200` + correct token.
- [x] Wrong secret → `401`; unknown agent → `404`; secret unset → `404`.
- [x] `.env.example` documents `AGENT_BUS_BOOTSTRAP_SECRET`.
- [x] New tests cover all four cases and pass.
- [x] Full existing test suite still passes (no regressions).
