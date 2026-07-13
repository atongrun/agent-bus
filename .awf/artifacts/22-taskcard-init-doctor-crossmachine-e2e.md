# Task Card

## Task ID

ABUS-INIT-DOCTOR-CROSSMACHINE-E2E-009

## Background

Agent Bus `init` and `doctor --listener` are already implemented on `master` by
PRs #10 and #11. The implementation generates a private, sourceable listener
environment, bridges the matching AWF role token without copying its value,
adds the relay host to `NO_PROXY`, records the Agent Workflow paths and OpenCode
flag, checks the environment, and warms the private-network path.

The first real Windows run exposed one deterministic implementation blocker:
`write_listener_env()` calls `Path.chmod(0o600)`, but Windows `os.chmod` cannot
create an owner-only ACL. The generated credential-bearing file remained
group-readable (`0666` as reported by Python/Git Bash). Skipping the assertion on
Windows would hide the vulnerability rather than fix it.

This rework fixes that blocker without giving the model any live token. The
executor implements and tests Windows ACL lockdown using a dummy fixture. The
reviewer then performs the real external-path `init` / `doctor --listener`
acceptance in a trusted shell and records only PASS/FAIL evidence.

## Goal

Make `agent-bus init` actually write an owner-only listener environment on
Windows, preserve POSIX `0600` behavior, and hand the reviewer a tested branch
for trusted-shell live acceptance.

## Scope

1. Start from the dispatched task branch at the exact event commit.
2. Run the existing automated tests for listener configuration.
3. In `client/listener_config.py`, keep `chmod(0o600)` on POSIX. On Windows,
   remove inherited ACL entries and grant Full control only to the current user
   via `icacls`, invoked as argv with `shell=False`.
4. Fail closed: if the Windows username is unavailable, `icacls` cannot start,
   or `icacls` returns non-zero, `init` must fail and must not report success for
   a potentially exposed credential file.
5. Add focused tests that lock the POSIX path, Windows `icacls` argv, and Windows
   failure behavior. Do not skip the permission assertion on Windows.
6. Run `init` only with the committed non-secret fixture and a dummy token. Do
   not run live authenticated `doctor`; that is reviewer-only.
7. Write the required ImplementationReport with test evidence and the explicitly
   deferred unrelated Windows poison-handler failures.

## Out of Scope

- Do not reimplement or redesign `init`, `doctor`, token bootstrap, or Agent
  Workflow dispatch.
- Do not add service installation, auto-start, listener supervision, log
  rotation, health daemons, or Runtime/Node lifecycle management.
- Do not add Git identity/bootstrap behavior or change repository credentials,
  deploy keys, tokens, SSH configuration, or server-side secrets.
- Do not fix the intermittent Windows `0xC0000142` process-start failure. If it
  occurs, record it, restart the one-shot command once, and continue.
- Do not clean old Agent Bus events or delete any remote E2E branches.
- Do not add dependencies, new configuration formats, or unrelated tests.
- Do not modify or skip permission assertions merely to make Windows green.
- Do not fix the unrelated Windows poison-handler path failures in this task.
- Do not treat DERP/peer-relay operation as failure when the warmup command and
  normal HTTP checks succeed.

## Working Context (self-contained)

- **Repository / path**: the existing Windows `agent-bus` checkout.
- **Base branch**: `master`.
- **Task branch**: `awf/init-doctor-crossmachine-e2e-009`.
- **Remote baseline**: `origin/master` at
  `1930a5b0a26c5fe74fd34546fdae4c0abc778dde`.
- **Dispatched task commit**: use the exact commit in the Agent Bus event; the
  runner must verify `origin/awf/init-doctor-crossmachine-e2e-009` still points
  to it before checkout.
- **Relevant merged commits**:
  - `9316999` — initial listener environment generation and diagnostics.
  - `a35cdc3` — Windows-safe bootstrap behavior.
  - `152a6f9` — accept healthy relay paths during warmup.
  - `c7548dc` — explicit role-token bridge selection.
- **Entry points**:
  - `client/cli.py`: `init_listener` and `doctor(..., listener=True)`.
  - `client/listener_config.py`: rendering, private write, environment checks,
    Windows Git Bash path conversion, and network warmup.
  - `tests/test_listener_config.py`: existing focused regression coverage.
  - `README.md`: documented receiver-side `init` / `doctor --listener` flow.
- **Executor acceptance fixture**:
  - `.awf/fixtures/init-doctor-awf-env.sh` contains no secret. It only asserts
    that the trusted runner supplied `AWF_CODER_TOKEN` and allows `init` to test
    its token-variable bridge without reading external user config.
- **Reference implementation pattern**: on Windows, use `USERNAME` (fallback
  `USER`) and run `icacls <path> /inheritance:r /grant:r <user>:F`. This task
  must fail closed when lockdown fails.
- **Executor environment**: no live Agent Bus token is available or required.
  Use only a literal dummy value for repo-local `init` verification.

## Constraints

- **Credential-output hard stop**: never run `env`, `printenv`, `set`,
  `Get-ChildItem Env:`, or any command that lists the process environment. Never
  `cat`, `type`, `head`, `grep`, or otherwise print either `dispatch.env` or a
  generated listener env. These commands can disclose live scoped tokens in
  non-interactive logs and are a task failure even if the value is later
  redacted from the report.
- Do not run live `agent-bus doctor --listener`; authenticated live verification
  is reviewer-only.
- If variable presence must be checked separately, use a fixed allowlist and
  print only `NAME=SET` / `NAME=MISSING`; never print values. Token-variable
  presence is proven by successful auth scope in `doctor`, not by echoing it.
- Run from a clean worktree. If the runner reports a dirty tree or unpushed
  commits, stop and report; do not reset, clean, or overwrite them.
- The executor process must not inherit any real `AGENT_BUS_TOKEN` or
  `AWF_*_TOKEN` value.
- The generated file must reference the role-token variable; it must not contain
  or print the token value.
- Redact private host values and personal absolute paths in the report. It is
  sufficient to report that each value is present and correct.
- A code change requires a reproducible acceptance failure attributable to the
  merged implementation. Environment-only failures are evidence, not permission
  to broaden the product.

## Acceptance Criteria

- [ ] POSIX writes still apply mode `0600`.
- [ ] Windows writes call `icacls` with an argv equivalent to
      `<path> /inheritance:r /grant:r <current-user>:F` and no shell.
- [ ] Missing username, process-start error, or non-zero `icacls` makes `init`
      fail instead of claiming the file is private.
- [ ] Focused listener-config tests pass on Windows without skipping the
      permission guarantee.
- [ ] `agent-bus init` succeeds with the repo-contained fixture and a literal
      dummy token; no live credential is used by the executor.
- [ ] Re-running `init` without `--force` refuses to overwrite the file and
      preserves its contents.
- [ ] The generated file contains a reference to the selected AWF role-token
      variable but contains no token value.
- [ ] `.awf/tmp/` is removed before completion; the committed branch contains no
      generated listener config or secret value.
- [ ] The reviewer separately repeats `init` / `doctor --listener` with the real
      external AWF and Agent Workflow paths and verifies ACLs; executor evidence
      must not claim that live check was performed.
- [ ] The required ImplementationReport exists before a review event is sent.

## Verification Commands

Run the repository commands through its existing Python environment. On Windows
Git Bash, prefer the checkout's `.venv/Scripts/python.exe` when present.

```bash
# Automated baseline
.venv/Scripts/python.exe -m unittest tests.test_listener_config -v

# Safe repo-local smoke with a dummy value only; do not run live doctor.
AWF_CODER_TOKEN=dummy-not-a-live-token .venv/Scripts/agent-bus.exe init \
  --agent coder \
  --server-url http://127.0.0.1:8800 \
  --awf-env .awf/fixtures/init-doctor-awf-env.sh \
  --repo-dir . \
  --script-dir scripts \
  --config .awf/tmp/listener-e2e.env

# Must refuse overwrite without --force.
AWF_CODER_TOKEN=dummy-not-a-live-token .venv/Scripts/agent-bus.exe init \
  --agent coder \
  --server-url http://127.0.0.1:8800 \
  --awf-env .awf/fixtures/init-doctor-awf-env.sh \
  --repo-dir . \
  --script-dir scripts \
  --config .awf/tmp/listener-e2e.env

# Remove generated local config before writing/committing the report.
rm -rf .awf/tmp
```

For redacted evidence, report variable names and boolean presence only. The
blanket environment/config-printing commands prohibited under **Constraints**
must not be used even temporarily.

## Rework vs. Escalate

- **Rework locally** only for the Windows ACL lockdown and its focused tests.
- **Escalate and stop** for missing credentials, unavailable Windows/VPS,
  network policy, repository permission, dirty/unpushed work, a requested scope
  expansion, or any need to change secrets, SSH keys, services, or old events.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Windows test is skipped instead of enforcing privacy | High | Require `icacls` argv and fail-closed tests |
| Evidence leaks token or private infrastructure details | High | Executor receives no live token; reviewer reports PASS/FAIL only |
| ACL command fails after file creation | High | Fail `init`; never print success for an unlocked file |
| Warmup uses DERP instead of direct connectivity | Low | Accept when warmup and HTTP/auth checks pass; direct path is not required |

## Required Output Artifacts

- `.awf/artifacts/23-implementation-report-init-doctor-crossmachine-e2e.md`
  containing:
  - exact commands run with secrets and private endpoints redacted;
  - automated test results;
  - each acceptance criterion result;
  - whether code changed and why;
  - any deferred environment issue.

---

## Planner Self-Check (complete BEFORE handing this card to an executor)

- [x] Goal is one concrete deliverable: Windows owner-only ACL enforcement plus
      reviewer-run live acceptance.
- [x] Scope is limited to the deterministic ACL blocker found by the real run.
- [x] Executor requires no live credential.
- [x] Out-of-scope service, credential, Git identity, old-event, and Windows DLL
      issues are explicit.
- [x] Every acceptance criterion is observable or command-verifiable.
- [x] Verification uses existing repository tools and adds no dependency.
- [x] Working context lets a fresh executor start without planner chat history.
- [x] Base, task branch, remote baseline, and event-commit authority are explicit.
