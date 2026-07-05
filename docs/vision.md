# Agent Bus Vision

Agent Bus starts as a small, durable event relay for agent-to-agent handoff. Its
long-term direction is broader: a lightweight coordination layer for local and
remote agents that need reliable communication, observable task state, and
recoverable collaboration.

## Near-Term Positioning

In v0.2, Agent Bus is a reliable, lightweight, secure event relay. It connects
AI agents and runtimes (such as Codex on macOS, OpenCode or Claude Code on
Windows, Codex CLI on Linux, or local scripts and test runners) with durable
events, simple HTTP APIs, SSE delivery, and explicit ACKs after successful
processing.

The goal is not millisecond latency. Normal delivery should happen within about
one second, and the more important property is that failed, offline, or
interrupted work is not silently lost.

## Mid-Term Positioning

Agent Bus should support both cross-machine and same-machine agent workflows.
For example, a local planner, a local verifier, and a remote Windows executor
should be able to coordinate through the same event model.

The mid-term product should make agent work:

- observable by a human,
- recoverable after crashes and disconnects,
- auditable through event history,
- easy to run on localhost, a small VPS, or a private LAN.

## Long-Term Positioning

The long-term vision is an agent coordination platform for larger collaborative
workflows. Possible future capabilities include:

- a lightweight task board,
- richer task states,
- simple workflow orchestration,
- agent role assignment,
- human approval gates,
- failure recovery and replay,
- historical run review.

These capabilities should grow out of the durable event model instead of
turning the project into a heavy platform too early.

## Principles

- Robustness before complexity.
- Recoverability before flashy real-time behavior.
- Second-level responsiveness is enough; lower latency is welcome but not the
  primary goal.
- Local-first and easy deployment by default.
- Security should be enabled by default, with advanced security added
  gradually.
- Prefer GitHub, files, and CLI integration before building a large all-in-one
  platform.

## v0.2 Non-Goals

Agent Bus v0.2 intentionally does not implement:

- a dashboard or kanban board,
- complex DAG orchestration,
- a clustered queue or external database,
- a Web UI,
- enterprise multi-tenant IAM,
- replacement for GitHub issues or pull requests.

For v0.2, Agent Bus only fills the reliable handoff gap between agents.

## Roadmap

- v0.2: reliable agent event relay with handler-success ACK.
- v0.3: local multi-agent workflows, pending/list/requeue, clearer task state.
- v0.4: lightweight read-only dashboard or board.
- v0.5: simple workflow orchestration with task graphs, human gates, and
  failure recovery.
- v1.0: unified local and remote agent coordination layer.
