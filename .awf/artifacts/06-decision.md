# Decision — ABUS-DOCTOR-001

> Artifact: Decision | Role: decider (user) | Date: 2026-07-11

## Decision: **APPROVE**

`agent-bus doctor` is approved. Correct, in-scope, verified against the real VPS,
regression-free (reviewer confirmed all criteria incl. token/VPS paths).

## Decider notes (carried forward, not blocking)

- **Model-strength caveat:** GLM-5.2 is itself a strong model. The high execution quality
  observed here is expected for GLM and must **not** be over-generalized into "the TaskCard
  was so good any weak model would succeed." The planner/executor split is not yet proven
  for genuinely weak executors.
- **Next experiment (decided):** the next TaskCard will be executed by OpenCode running
  **DeepSeek V4 Flash** — a cheaper/weaker executor — to stress-test whether the method
  (and how concise the card can be) holds when the executor is weak. Escalation/rework rate
  will be the signal.

## Run outcome

Artifact chain complete for M1: Baseline → ArchitectureRecord → TaskCard →
ImplementationReport → ReviewReport → Decision. First real Agent Workflow loop closed on a
real project (Agent Bus), executed by a local coding agent dispatched over the user's VPS.
