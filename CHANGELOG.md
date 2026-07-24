# Changelog

All notable Agent Bus changes are recorded here. Agent Bus is not currently
published on PyPI; release artifacts and source history are published through
GitHub.

## [Unreleased]

### Added

- Docker Compose server deployment with a non-root runtime, persistent SQLite
  volume, localhost-only default publication, healthcheck, and an idempotent
  installer that generates protected per-agent tokens on first use.
- Automated Docker acceptance covering installation, health, durable event
  delivery, container recreation, ACK, and queue cleanup.
- A cross-platform `agent-bus setup` command that protects the agent
  credential, configures a native context, and verifies it with `doctor`.

### Changed

- The README now presents Docker and systemd as equal one-command deployment
  choices, uses the same uv-managed client setup on macOS, Linux, and Windows,
  and keeps manual setup in the installation guide.

## [0.2.0] - 2026-07-17

The first official release establishes Agent Bus as a lightweight,
runtime-agnostic event relay for a few trusted agents across localhost or a
private network.

### Added

- Durable SQLite-backed event creation, pending replay, SSE delivery, and
  recipient ACK with at-least-once semantics.
- Per-agent bearer-token authorization for sending, streaming, inspection,
  ACK, failed-attempt recording, and requeue; the shared token remains a
  development and migration fallback.
- Named client contexts that store server/agent/credential references without
  storing token values, plus `doctor` connectivity and round-trip diagnostics.
- Durable failure recovery: server-side attempt counts and last errors persist
  across listener processes, terminal failed events are recipient-inspectable,
  and explicit requeue preserves recovery evidence.
- Tailscale/private-network deployment guidance, safe bootstrap-token handling,
  and client credential-file practices for POSIX and Windows.

### Changed

- Listener handlers ACK only after successful completion. Failed or timed-out
  handling remains replayable until the configured terminal threshold.
- ACK and failed-attempt transitions use the observed persisted retry count to
  reject stale updates without introducing claim/lease semantics.
- The root README now follows the shortest new-user path and keeps Worker
  Runtime responsibilities outside Agent Bus Core.

### Boundaries

- Delivery is at least once, not exactly once. Handlers remain responsible for
  application-level idempotency.
- Agent Bus does not provide competing-consumer claims or leases, a built-in
  Worker Runtime, workflow/Git/prompt/AI execution, a UI, or an external queue.
- v0.2.0 is not published to PyPI; clients install from a source checkout.

[Unreleased]: https://github.com/atongrun/agent-bus/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/atongrun/agent-bus/releases/tag/v0.2.0
