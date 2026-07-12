# Task Card

## Task ID

ABUS-SERVER-FAIL-PERSIST-008

## Background

When a listener's handler fails repeatedly on the same event (a "poison event"),
the listener today only tracks the failure count **in memory**
(`client/cli.py` `failure_counts`). After N attempts it adds the event id to an
in-memory `skipped_ids` set and moves on — but it never tells the server. So on a
process restart (crash, service KeepAlive, `--once`) the count resets to zero and
the poison event is re-delivered and re-run from scratch. For an AI executor that
means re-editing code, re-committing, and re-spending API quota on a task that was
already given up on.

The server schema is already prepared for this but unused: `server/db.py` defines
`status IN ('pending','delivered','acked','failed')` and a `retry_count` column,
yet **no code ever writes `failed`** (`retry_count` is always 0) and there is no
endpoint to set it — it is dead scaffolding. `server/events.py:91` even has an
optimistic comment ("already acked or failed") for a state the code can't reach.

This card makes the server actually persist a failed/poison event, so a
poison event is recorded once and not silently re-run forever. (Local
idempotency keyed on task_id is a *separate, later* card — NOT this one.)

## Goal

Make failed events durable on the server: add a `mark_failed` DB operation, a
`POST /events/{id}/fail` endpoint, and a `last_error` column; and make the
listener call that endpoint when it gives up on a poison event. After this, a
poison event that exhausts its attempts is `status='failed'` on the server (with
`retry_count` incremented and `last_error` recorded) instead of staying pending.

## Scope

**Server (`server/`):**
- `db.py`: add a `last_error TEXT` column to the `events` table. Add it to the
  `CREATE TABLE` in `init_db()`, AND add an idempotent migration for existing
  databases: attempt `ALTER TABLE events ADD COLUMN last_error TEXT` inside a
  try/except that swallows the "duplicate column" error (so re-running `init_db`
  on an old db is safe).
- `db.py`: add `mark_failed(event_id: int, last_error: str | None) -> bool` that
  sets `status='failed'`, `retry_count = retry_count + 1`, and `last_error = ?`,
  **only when the current status is in ('pending','delivered')**. Return
  `cursor.rowcount > 0`. Mirror the style of the existing `ack_event()`.
- `events.py`: add `POST /events/{event_id}/fail`. Request body: optional
  `{"error": "<text>"}`. Behavior, mirroring the existing `ack` endpoint:
  - event not found → `404`.
  - scope check via the existing `_require_agent(auth, row["to_agent"], "fail events")`.
  - already `acked` → `409` (cannot fail an acked event).
  - otherwise call `mark_failed(...)`; on success return
    `{"id": ..., "status": "failed", "retry_count": ..., "last_error": ...}`.
- `events.py`: add `"last_error": row["last_error"]` to `_row_to_response`.
- `models.py`: if you add a request model for the body (e.g. `EventFail` with an
  optional `error: str | None = None`), put it here, matching existing models.

**Listener (`client/cli.py`):**
- Add `_post_fail(base_url: str, token: str, event_id: int, error: str) -> bool`
  modeled exactly on the existing `_post_ack` (same httpx client, `get_headers`,
  timeout, diagnostic print). POST to `/events/{event_id}/fail` with JSON body
  `{"error": error}`.
- At the **three** places where the listener decides an event is poison and adds
  it to `skipped_ids` after `failure_counts[...] >= max_event_attempts` (the
  handler-template-error branch, the handler-run-failure branch, and the
  JSON-decode-error branch), call `_post_fail(url, token, event_id, <reason>)`
  BEFORE `skipped_ids.add(...)`. Use the existing human-readable skip reason
  string as the `error` text. The url/token are `ctx.obj["url"]` / `ctx.obj["token"]`.

## Out of Scope

- Do NOT add local idempotency (task_id / idempotency_key), a client-side
  "already done" store, or any dedup — that is a separate later card.
- Do NOT add a distinct `held`/`dead-letter` status or a retry/redrive mechanism.
  Just use the existing `failed` status.
- Do NOT change `ack`/`stream`/`pending`/`create` behavior, `verify_token`, or the
  poison in-memory counting logic itself (you are *adding* a server notification,
  not replacing the counter).
- Do NOT add any dependency (no MQ, Redis, migration framework). Plain SQLite +
  `ALTER TABLE` only.
- Do NOT touch deployment/systemd/service files.

## Working Context (self-contained)

- **Repository / path**: the Agent Bus repo checked out on this machine
  (Windows: `D:\path\to\agent-bus`). Work on the branch this card was dispatched on
  (`awf/server-fail-persist`). Do NOT work on `master`.
- **Entry points & relevant files**:
  - `server/db.py` — SQLite layer. `init_db()` has the `CREATE TABLE events`
    (status CHECK already includes `'failed'`; `retry_count` column already
    exists). `ack_event()` is the exact pattern to mirror for `mark_failed()`:
    a guarded `UPDATE ... WHERE id = ? AND status IN (...)` returning
    `cursor.rowcount > 0`. Connections come from `get_db()` (a commit/rollback
    context manager).
  - `server/events.py` — `POST /events/{id}/ack` (`acknowledge_event`) is the
    template for the new `/fail` route: it does `get_event`, `_require_agent`,
    the already-acked short-circuit, then the DB call + `HTTPException` on
    failure. `_row_to_response(row)` is where response fields are assembled.
    `_require_agent(auth, agent, action)` enforces per-agent token scope.
  - `server/models.py` — Pydantic models (`EventCreate` is the existing example).
  - `client/cli.py` — `_post_ack(base_url, token, event_id) -> bool` (~line 53)
    is the exact template for `_post_fail`. `get_headers(token)` builds auth
    headers. The `listen` command's inner `process_event` has the three poison
    branches; each does `failure_counts[...] += 1` then, on reaching
    `max_event_attempts`, `skipped_ids.add(event_id)` and prints a skip message.
  - `tests/test_poison_event.py` — existing poison test harness
    (`_run_listen(replays, max_attempts, handler_cmd)`, `_always_fail_handler`).
    Extend it. `tests/test_auth.py` shows the server-test style
    (`fastapi.testclient.TestClient(app)`, `patch.dict(os.environ, ...)`).
- **Relevant existing behavior (must not regress)**: `/health`, `POST /events`,
  `POST /events/{id}/ack`, `GET /events/pending`, `GET /events/stream`, and
  per-agent token scoping all keep working.
- **Project rules**: see this project's `AGENTS.md` for stack, conventions, commands.

## Constraints

- `mark_failed` must be a no-op (return False) if the event is already `acked` or
  already `failed` — only `pending`/`delivered` transition to `failed`.
- `last_error` migration must be idempotent: safe to run `init_db()` against a db
  that already has the column (catch the duplicate-column error, don't crash).
- `_post_fail` must never raise out of the listener loop: on network error it
  prints a diagnostic and returns False (same robustness as `_post_ack`).
- Do not log tokens.

## Acceptance Criteria

- [ ] `POST /events/{id}/fail` on a pending/delivered event → `200`, and the event
  is then `status='failed'`, `retry_count` incremented by 1, `last_error` set.
- [ ] `POST /events/{id}/fail` on a non-existent id → `404`.
- [ ] `POST /events/{id}/fail` on an already-`acked` event → `409`.
- [ ] Scope check: a token scoped to agent A cannot fail an event addressed to
  agent B → `403` (non-legacy mode).
- [ ] `_row_to_response` / GET responses include `last_error`.
- [ ] `init_db()` run twice in a row (simulating an existing db) does not error
  (idempotent `last_error` migration).
- [ ] Extended `tests/test_poison_event.py`: after a poison event exhausts
  `max_event_attempts`, the event's server-side status is `failed` (not pending).
- [ ] The full existing test suite still passes (no regressions).

## Verification Commands

```bash
# From the agent-bus repo root, using the project venv.
# Windows (git-bash):
.venv/Scripts/python.exe -m pytest tests/ -q

# Targeted:
.venv/Scripts/python.exe -m pytest tests/test_poison_event.py -q
```

## Rework vs. Escalate

- **Rework locally** only for deterministic failures: compile/test failure, a
  failed acceptance criterion, missing required evidence, or a clear violation of
  this card.
- **Escalate (stop and report)** if: the goal is ambiguous, required context is
  missing, there is an architecture/scope question, or a change would exceed
  **Out of Scope** (e.g. you find yourself wanting to add idempotency or a new
  status — stop and report instead).

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Migration crashes on existing db (duplicate column) | Med | Wrap `ALTER TABLE` in try/except swallowing the duplicate-column error; test `init_db()` twice |
| `_post_fail` network error kills the listen loop | Med | Mirror `_post_ack`: catch, print, return False; never propagate |
| Regressing ack/stream/scope | Med | Do not touch those paths; run full suite |
| Marking an acked event failed (data corruption) | Med | `mark_failed` guarded `WHERE status IN ('pending','delivered')`; endpoint 409s on acked |

## Required Output Artifacts

- ImplementationReport at `.awf/artifacts/22-implementation-report.md` (what
  changed, commands run + results, any deviations).

---

## Planner Self-Check (complete BEFORE handing this card to an executor)

- [x] Goal is a single concrete deliverable (server persists failed events + listener notifies).
- [x] Scope and Out of Scope are explicit and non-overlapping (idempotency explicitly deferred).
- [x] Every Acceptance Criterion is verifiable by a command or observable check.
- [x] Verification Commands are real commands from the project (pytest via the venv).
- [x] Working Context lets a fresh-session executor start without the planner's chat history.
- [x] This task advances the current milestone (server-side failure persistence — the "stop the bleeding" step).
