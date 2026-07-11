# Decision — ABUS-EXIT-002 (Graceful Exit)

> Role: decider (user) | Date: 2026-07-11

## Decision: **APPROVE**

Graceful exit for `agent-bus listen` is approved after one bounded rework.

- `control:shutdown` remote-stop (the Hermes scenario) + optional `target` name-match: works,
  verified against the VPS.
- `--exit-after-idle`: bug found in review, reworked by DeepSeek Flash (~30s), re-verified PASS.

## Experiment outcome (weak-model executor)

Confirmed: "strong planning + weak execution + strong review gate" holds. DeepSeek V4 Flash,
given the same-detail card, got architecture/requirements right, made one API-usage bug, and
fixed it in one bounded rework after reading the review. Rework rate is non-zero but cheap and
controllable. Review is the essential safety net when the executor is weak.

## Run outcome

Second full Agent Workflow loop closed on Agent Bus, including a real rework cycle:
Baseline → ArchitectureRecord → TaskCard → Impl(DeepSeek) → Review(request_changes) →
Rework(DeepSeek) → Review(PASS) → Decision.
