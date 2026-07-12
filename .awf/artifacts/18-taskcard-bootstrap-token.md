# Task Card

## Task ID

ABUS-BOOTSTRAP-TOKEN-006

## Background

Agent Workflow's `awf_bootstrap` helper needs to fetch each machine's Agent Bus
role token when a new/hand-off machine comes online. Today it pulls the tokens
over SSH from the VPS `/etc/agent-bus/.env`, which forces every executor machine
to hold VPS SSH access and uses a fragile nested-ssh path. The agreed direction
is a plain HTTP fetch: a machine presents a single low-privilege *bootstrap
secret* over `curl` and receives its high-privilege *role token* in return. This
is the standard secret-bootstrapping pattern (Vault, cloud metadata). This task
adds that endpoint to the Agent Bus server so the bootstrap script can switch
from SSH to `curl`.

## Goal

Add an HTTP endpoint `POST /bootstrap/token` to the Agent Bus server that
exchanges a valid bootstrap secret (from a new env var) for a named agent's
role token, so a machine can `curl` its token without SSH.

## Scope

- Add `POST /bootstrap/token` to the server.
- Request body: `{"agent": "<name>"}` (e.g. `coder`).
- Auth: an `X-Bootstrap-Secret: <secret>` request header, compared against a new
  environment variable `AGENT_BUS_BOOTSTRAP_SECRET` using `secrets.compare_digest`.
- Response `200`: `{"agent": "<name>", "token": "<role-token>"}` where the token
  is looked up from the existing `get_agent_tokens()` map in `server/auth.py`.
- Error behavior:
  - If `AGENT_BUS_BOOTSTRAP_SECRET` is unset/empty → `404` (feature disabled; do
    NOT expose the endpoint when no secret is configured).
  - Missing/incorrect `X-Bootstrap-Secret` → `401`.
  - `agent` not present in `AGENT_BUS_AGENT_TOKENS` → `404`.
- Document the new env var in `.env.example`.
- Add tests to `tests/test_auth.py` (or a new `tests/test_bootstrap_token.py`).

## Out of Scope

- Do NOT change the existing role-token auth (`verify_token`) or any existing
  route behavior.
- Do NOT add token *rotation*, expiry, one-time-use, or rate limiting (Later).
- Do NOT modify the `awf_bootstrap.py` client script (a separate task switches it
  from SSH to curl once this endpoint exists).
- Do NOT change deployment/systemd or set the secret's real value anywhere in the
  repo.

## Working Context (self-contained)

- **Repository / path**: the Agent Bus repo checked out on this machine
  (Windows: `D:\Work\AI\01_Project\agent-bus`). Work on the branch this card was
  dispatched on.
- **Entry points & relevant files**:
  - `server/auth.py` — has `get_agent_tokens() -> dict[str, str]` which parses
    `AGENT_BUS_AGENT_TOKENS` (`agent=token,...`). Reuse it to look up the token.
    Also uses `secrets.compare_digest` — follow the same constant-time-compare style.
  - `server/main.py` — FastAPI `app`; mounts routers via `app.include_router(...)`
    and defines the unauthenticated `/health` route. Mount the new route here, or
    add it to a small new router and include it. The endpoint is at the app root
    (`/bootstrap/token`), NOT under the `/events` prefix.
  - `server/events.py` — reference for how existing `@router.post(...)` endpoints
    read the body and raise `HTTPException(status_code=..., detail=...)`.
  - `server/models.py` — Pydantic models live here; add a request model
    (e.g. `BootstrapTokenRequest` with an `agent: str` field) if you use one.
  - `.env.example` — documents env vars; add `AGENT_BUS_BOOTSTRAP_SECRET` with an
    explanatory comment and a placeholder value (never a real secret).
  - `tests/test_auth.py` — existing auth tests use
    `unittest.IsolatedAsyncioTestCase` + `patch.dict(os.environ, {...}, clear=True)`.
    Match that style. To test an HTTP route, `fastapi.testclient.TestClient(app)`
    is available via FastAPI/Starlette.
- **Relevant existing behavior (must not regress)**: `/health` (no auth),
  `POST /events`, `POST /events/{id}/ack`, `GET /events/pending`, `GET /events/stream`
  all keep working. Per-agent token scoping via `verify_token` is unchanged.
- **Project rules**: see this project's `AGENTS.md` for stack, conventions, and commands.

## Constraints

- Use `secrets.compare_digest` for the secret comparison (no `==`).
- Read `AGENT_BUS_BOOTSTRAP_SECRET` from the environment at request time (like
  `get_agent_tokens()` reads its env var), not at import time.
- The endpoint must NEVER log or echo the bootstrap secret or the returned token.
- When the feature is disabled (no secret configured), the endpoint must behave as
  if it does not exist (`404`) — do not reveal that a secret is required.

## Acceptance Criteria

- [ ] `POST /bootstrap/token` with a correct `X-Bootstrap-Secret` and
  `{"agent":"coder"}` returns `200` and `{"agent":"coder","token":"<coder-token>"}`
  matching the value in `AGENT_BUS_AGENT_TOKENS`.
- [ ] Wrong secret → `401`; unknown agent (valid secret) → `404`;
  `AGENT_BUS_BOOTSTRAP_SECRET` unset → `404`.
- [ ] `.env.example` documents `AGENT_BUS_BOOTSTRAP_SECRET`.
- [ ] New tests cover all four cases above and pass.
- [ ] The full existing test suite still passes (no regressions).

## Verification Commands

```bash
# From the agent-bus repo root, using the project venv.
# Windows (git-bash):
.venv/Scripts/python.exe -m pytest tests/ -q
# (equivalently: python -m unittest discover -s tests)

# Targeted:
.venv/Scripts/python.exe -m pytest tests/test_auth.py tests/test_bootstrap_token.py -q
```

## Rework vs. Escalate

- **Rework locally** only for deterministic failures: compile/test failure, a
  failed acceptance criterion, missing required evidence, or a clear violation of
  this card.
- **Escalate (stop and report)** if: the goal is ambiguous, required context is
  missing, there is an architecture/scope question, or a change would exceed
  **Out of Scope**.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Endpoint leaks tokens if secret is weak/guessable | High | Constant-time compare; disabled (404) unless a secret is explicitly configured; no rate-limit is Later but documented |
| Accidentally exposing the endpoint when unconfigured | Med | Return 404 when `AGENT_BUS_BOOTSTRAP_SECRET` is unset |
| Regressing existing auth/routes | Med | Do not touch `verify_token`/`/events`; run full suite |

## Required Output Artifacts

- ImplementationReport at `.awf/artifacts/19-implementation-report.md` (what
  changed, commands run + results, any deviations).

---

## Planner Self-Check (complete BEFORE handing this card to an executor)

- [x] Goal is a single concrete deliverable (one new endpoint + its env var + tests).
- [x] Scope and Out of Scope are explicit and non-overlapping.
- [x] Every Acceptance Criterion is verifiable by a command or observable check.
- [x] Verification Commands are real commands from the project (pytest via the venv).
- [x] Working Context lets a fresh-session executor start without the planner's chat history.
- [x] This task advances the current milestone (curl-based token bootstrap).
