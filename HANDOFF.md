# Repository Handoff

> Current through the 2026-07-28 Dousansi dogfood stop. The authoritative branch is `master` at
> the live Git ref. This file contains no private endpoint, credential, host, personal path, or event
> payload data.

## Product Boundary

Agent Bus is a durable, at-least-once event relay. It owns persistence, recipient-scoped delivery,
ACK, failed-attempt accounting, and reconnect replay. A Worker Runtime owns workspace selection,
model invocation, idempotency, workflow stage, rework budget, and Git/PR policy. Do not turn a
transport fix into a workflow engine.

Read [`README.md`](README.md), [`docs/protocol.md`](docs/protocol.md),
[`docs/worker.md`](docs/worker.md), and [`docs/recommended-practices.md`](docs/recommended-practices.md)
before changing delivery behavior.

The current P1-3 client addition introduces the local
`agent-bus.listen.on-argv.v1` consumer contract. `listen --on-argv TYPE ARGV_JSON` validates a
non-empty string array before connecting, replaces placeholders within existing argv tokens, and
launches the result through the same `shell=False` process boundary. Legacy `--on TYPE COMMAND`
remains supported so Agent Bus can be upgraded before Agent Workflow. Server protocol/storage,
delivery, durable failure, ACK and requeue behavior are unchanged. The pinned peer contract is
`awf.handler-argv.v1`; upgrade Bus before Workflow and roll back Workflow before Bus.

## Latest Dogfood Evidence

- The v0.3 client reconnect repair is merged on `master`. A daemon listener now uses a bounded idle
  read timeout and reconnects with backoff; explicit `--exit-after-idle` still exits. This restores
  replay of unacknowledged work after a stale SSE stream without changing server storage or protocol.
- The repair was verified with focused reconnect regressions, full Mac tests, a fresh Windows client
  checkout, static checks, CI, independent review, and an exact-version rollout check. The server
  was intentionally not changed.
- A controlled downstream recovery demonstrated the reconnect path and was then stopped before any
  commit, push, ACK, or reviewer event. Do not use preserved downstream events as manual test input.

## Proven Limitations And Operating Rules

1. **`delivered` is not proof that a handler began.** The server can mark an event delivered before
   the client has parsed and processed its SSE frame. A same-stream high-water mark cannot replay
   that frame; reconnect replay is the recovery path. Treat delivery as at-least-once and keep
   handlers idempotent.
2. **A daemon must reconnect.** Long-lived listeners must not rely on an indefinitely silent SSE
   stream for recovery. The merged client repair covers the default CLI daemon path; custom clients
   need equivalent bounded reconnect behavior.
3. **Redelivery is transport behavior, not workflow authorization.** A failed or disconnected event
   may be redelivered before a Workflow runtime can enforce a TaskCard's rework budget. The trusted
   Worker Runtime must persist and check its own attempt/budget state before invoking a model.
4. **One logical identity needs one active consumer unless the adapter is idempotent.** Agent Bus does
   not coordinate worker leases or workflow routes. Concurrent listeners can legitimately observe
   the same unacknowledged work.
5. **Payload and historical-event safety remain adapter policy.** The relay cannot decide which
   event is safe to inspect, ACK, requeue, or replay. Operators must preserve evidence and follow
   the owning Workflow's terminal-recovery procedure.

## Next Evidence-Driven Work

1. Do not alter server transport semantics without a new reproducible transport failure and a
   protocol-level reason; the stale-stream defect was repaired client-side.
2. After Agent Workflow adds its pre-invocation route/budget gate, run one fresh disposable test
   event that proves reconnect replay cannot exceed the Workflow-owned budget.
3. Keep reliability work limited to observed failures: reconnect behavior, idempotency guidance,
   listener visibility, and safe recovery evidence. Do not add a scheduler, model runner, or
   workflow state machine to Agent Bus.

## Standing Rules

- Keep persistent SQLite data and historical event evidence intact.
- ACK only after successful handling; use explicit failure reporting on handler failure.
- Never expose bearer-token transport publicly or place token values in logs, commits, or handoff.
- Feature branch, PR, CI, and review remain required for repository changes.
