# Task Card

## Task ID

ABUS-INIT-DOCTOR-CROSSMACHINE-E2E-009

## Background

Agent Bus `init` and `doctor --listener` are already implemented on `master` by
PRs #10 and #11. The implementation generates a private, sourceable listener
environment, bridges the matching AWF role token without copying its value,
adds the relay host to `NO_PROXY`, records the Agent Workflow paths and OpenCode
flag, checks the environment, and warms the private-network path.

The remaining gap is not another implementation pass. It is a real
fresh-session acceptance run on the Windows executor that previously required
hand-assembled environment variables. This card verifies that the merged
commands replace that manual reconstruction and records evidence. Code changes
are allowed only when the acceptance run exposes a deterministic blocker in the
existing `init` / `doctor --listener` path.

## Goal

From a fresh Windows Git Bash session, use the merged `agent-bus init` output to
load the complete coder-listener environment and make `agent-bus doctor
--listener` pass against the existing private Agent Bus server, without manually
exporting the values that `init` is responsible for.

## Scope

1. Start from the dispatched task branch at the exact event commit.
2. Run the existing automated tests for listener configuration.
3. In a fresh Windows Git Bash session, run `agent-bus init` for the coder role
   using the existing local AWF environment, agent-bus checkout, Agent Workflow
   scripts directory, and private Agent Bus URL.
4. Source only the generated listener environment, then run `agent-bus doctor
   --listener`.
5. Record redacted evidence showing generated-file permissions, required
   variable presence, proxy bypass, path values, warmup result, server health,
   and auth-scope result. Never record token values.
6. If and only if a deterministic defect in the merged `init` / `doctor
   --listener` implementation blocks an acceptance criterion, make the smallest
   fix and add a focused regression test for that defect.

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
- **Existing local inputs**: use the already provisioned AWF dispatch env,
  private Agent Bus URL, checkout paths, and role token. Do not print, copy into
  the repository, or transmit credential values in reports.

## Constraints

- Run from a clean worktree. If the runner reports a dirty tree or unpushed
  commits, stop and report; do not reset, clean, or overwrite them.
- Use a genuinely fresh Git Bash process for acceptance. Do not inherit a shell
  that already contains manually exported `AGENT_BUS_*`, `AWF_*`, `NO_PROXY`, or
  OpenCode listener variables.
- The generated file must reference the role-token variable; it must not contain
  or print the token value.
- Redact private host values and personal absolute paths in the report. It is
  sufficient to report that each value is present and correct.
- A code change requires a reproducible acceptance failure attributable to the
  merged implementation. Environment-only failures are evidence, not permission
  to broaden the product.

## Acceptance Criteria

- [ ] Existing focused tests pass before the real-machine run.
- [ ] `agent-bus init` succeeds in a fresh Windows Git Bash session using the
      documented arguments and writes the configured listener env with private
      permissions.
- [ ] Re-running `init` without `--force` refuses to overwrite the file and
      preserves its contents.
- [ ] The generated file contains a reference to the selected AWF role-token
      variable but contains no token value.
- [ ] After sourcing only the generated file, `AGENT_BUS_AGENT`,
      `AGENT_BUS_TOKEN`, `AWF_REPO_DIR`, `AWF_SCRIPT_DIR`,
      `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS`, `NO_PROXY`, and the network
      warmup settings are present and correct.
- [ ] `agent-bus doctor --listener` exits `0` and reports PASS for listener
      environment, network warmup, server health, and auth scope.
- [ ] No manual exports are required after sourcing the generated listener env.
- [ ] If no implementation blocker is found, the branch contains only this
      TaskCard and the required evidence report; no production code is changed.

## Verification Commands

Run the repository commands through its existing Python environment. On Windows
Git Bash, prefer the checkout's `.venv/Scripts/python.exe` when present.

```bash
# Automated baseline
.venv/Scripts/python.exe -m pytest tests/test_listener_config.py -q
.venv/Scripts/python.exe -m pytest tests/ -q

# Generate into a task-specific temporary path so existing user config is not
# overwritten. Replace placeholders locally; do not paste secrets into argv.
.venv/Scripts/agent-bus.exe init \
  --agent coder \
  --server-url http://<private-agent-bus-host>:8800 \
  --awf-env ~/.config/awf/dispatch.env \
  --repo-dir <agent-bus-checkout> \
  --script-dir <agent-workflow-checkout>/scripts \
  --config ~/.config/agent-bus/listener-e2e.env

# Must refuse overwrite without --force.
.venv/Scripts/agent-bus.exe init \
  --agent coder \
  --server-url http://<private-agent-bus-host>:8800 \
  --awf-env ~/.config/awf/dispatch.env \
  --repo-dir <agent-bus-checkout> \
  --script-dir <agent-workflow-checkout>/scripts \
  --config ~/.config/agent-bus/listener-e2e.env

# Open a new Git Bash process, then source only the generated file.
source ~/.config/agent-bus/listener-e2e.env
.venv/Scripts/agent-bus.exe doctor --listener
```

For redacted evidence, report variable names and boolean presence only. Do not
run commands that print the environment or token values wholesale.

## Rework vs. Escalate

- **Rework locally** only for a deterministic failure in the existing `init` or
  `doctor --listener` code that directly prevents an acceptance criterion. Add
  one focused regression test and rerun the full suite.
- **Escalate and stop** for missing credentials, unavailable Windows/VPS,
  network policy, repository permission, dirty/unpushed work, a requested scope
  expansion, or any need to change secrets, SSH keys, services, or old events.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Existing shell variables make a broken generated config appear healthy | High | Use a genuinely fresh Git Bash process and source only the generated file |
| Evidence leaks token or private infrastructure details | High | Report names/presence/results only; never dump environment or file contents |
| Environment problem is misclassified as a product defect | Medium | Reproduce and attribute before changing code; otherwise escalate |
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

- [x] Goal is one concrete deliverable: real Windows fresh-session acceptance
      of the already merged `init` / `doctor --listener` path.
- [x] Scope does not duplicate the merged implementation.
- [x] Code changes are gated on a deterministic acceptance blocker.
- [x] Out-of-scope service, credential, Git identity, old-event, and Windows DLL
      issues are explicit.
- [x] Every acceptance criterion is observable or command-verifiable.
- [x] Verification uses existing repository tools and adds no dependency.
- [x] Working context lets a fresh executor start without planner chat history.
- [x] Base, task branch, remote baseline, and event-commit authority are explicit.
