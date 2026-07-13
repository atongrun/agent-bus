# TaskCard: Executor sync-gate cross-machine proof

## Objective

Prove the real Mac-to-Windows executor path on an isolated Agent Bus task branch. Produce only
the requested evidence artifacts; do not change product source, tests, configuration, or dependencies.

## Working Context

- Repository / path: the runner-provided `agent-bus` checkout.
- Base branch: `master`.
- Task branch: `awf/executor-sync-gate-e2e-002`.
- Dispatched task commit: the exact `commit` value in the Agent Bus event.
- Remote baseline: `origin/master` at task-branch creation time.
- The runner must finish its clean-worktree, fetch/prune, exact-commit, and checkout preflight
  before OpenCode starts. Do not reset, clean, stash, or overwrite another session's work.

## Scope

Create exactly these two files:

1. `docs/tasks/executor-sync-gate-e2e-report.md`
2. `docs/tasks/executor-sync-gate-e2e.done`

The report must record the starting branch and commit, state that no product source or tests were
changed, and list the verification commands with results. The done marker must contain exactly:

```text
executor-sync-gate-e2e: complete
```

## Acceptance Criteria

- OpenCode runs on Windows after exact remote-commit checkout.
- Only this TaskCard and the two requested evidence artifacts differ from `origin/master`.
- The runner commits and pushes executor output to the task branch.
- The coder emits `task:awf-review` with the pushed commit.

## Verification Commands

```bash
git branch --show-current
git status --short
git diff --name-only origin/master...HEAD
```

## Stop Conditions

- Stop and report if preflight reports a dirty worktree, unpushed commits, branch drift, or commit mismatch.
- Do not repair infrastructure, broaden tests, or modify product files.
