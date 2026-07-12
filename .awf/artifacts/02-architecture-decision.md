# Agent Bus — Architecture Decision Record

> Artifact: ArchitectureRecord | Role: architect (Claude Code, single-architect mode)
> Date: 2026-07-11 | Status: **frozen** (only the scope M1 needs)
> Method: constitution.md §4. Freeze only what the next milestone requires; the rest is `Later`.

## Inputs to this decision

1. **Real execution findings** (see 01-baseline P1–P4).
2. **Architect recommendations** (Claude Code): move broadcast → work-queue (lease);
   add `doctor` + one-command listener; keep runtime-agnostic relay as the differentiator
   (do NOT rebuild into OpenHands/Baton-style sandbox orchestrator).
3. **User direction**: pursue **simple + easy to use**, **human involvement minimal**.
   Execution end = local OpenCode this project; cross-machine deferred to next project.

## Guiding principle (unchanged from project vision)

Agent Bus stays a **runtime-agnostic relay**, not an orchestrator. Its differentiation is
cross-machine, tool-agnostic transport — no competitor occupies that. We borrow *queue
semantics* and *ergonomics* from mature tools without absorbing their scope. Every change
below must preserve: relay-only core, single-node SQLite+SSE, no Git/AI/DAG in core.

## The four problems, and the decided direction for each

| # | Problem | Direction | When |
|---|---------|-----------|------|
| P1 | No diagnostics; setup is manual | Add `agent-bus doctor` self-check (URL, token, health, auth scope, send/pending/ack roundtrip). Additive CLI only — no server/protocol change. | **M1 (now)** |
| P3 | No graceful/remote exit; service lingers after tool exits | listener gains `--exit-after-idle` (self-exit when idle) + optional `control:shutdown` event handling (remote exit via the existing event channel — user's own idea). | Later (M2 candidate) |
| P2 | Broadcast, not work-queue; two same-name workers both run a task | Introduce a **lease/claim** so each task is delivered to exactly one worker (competing-consumers). Touches db + delivery semantics — higher risk. | Later |
| P4 | Stale events replay forever; clog `--once` | Event TTL / requeue-and-expire ergonomics. Related to P2's lease work. | Later |

**Note on coupling (recorded, not solved now):** P2 (instance addressing) and P3 (exit a
*specific* service) share one root — Agent Bus addresses by *agent name*, not *worker
instance*. When P2/P3 are planned, give each listener an instance id (e.g. `coder@mac`).
Out of scope for M1.

## Frozen decisions for M1 (`agent-bus doctor`)

- **D1. Additive, non-invasive.** `doctor` is a new CLI subcommand in `client/cli.py`. It
  MUST NOT change the server, the DB schema, the wire protocol, or any existing command.
- **D2. Read-first, safe self-test.** `doctor` checks, in order: config present (URL/token/
  agent) → server `/health` reachable → auth scope valid (can list own pending). An
  end-to-end send→pending→ack self-test is **opt-in via a flag** (e.g. `--send-test`),
  because it writes a real event. Default `doctor` is read-only and creates no events.
- **D3. Human-readable, actionable output.** Each check prints PASS/FAIL plus, on failure,
  the concrete fix (which env var / which command). This is the "reduce human involvement"
  payoff — the tool tells you what's wrong instead of you SSH-probing.
- **D4. Exit code contract.** `doctor` exits 0 if all non-optional checks pass, non-zero
  otherwise — so it can gate scripts.
- **D5. No new dependencies.** Reuse existing `httpx`, `click`, config loading
  (`get_config()` at `client/cli.py:21`). Match the file's existing style.

## Convergence

Single-architect mode. One round. No unresolved architecture question blocks M1.
Status: **frozen**. Reopen only if implementing `doctor` reveals the core path can't run.

## Explicitly Later (do not let these block M1)

- P2 work-queue lease, P3 exit mechanism, P4 TTL, instance addressing, retry dashboard,
  tray app. All deferred. Optional improvements never block M1 (constitution §7).
