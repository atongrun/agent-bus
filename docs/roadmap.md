# Product Roadmap

This roadmap keeps Agent Bus focused on durable messaging first. The near-term
goal is not to build a platform UI or workflow engine. The goal is to make
cross-runtime agent handoff reliable enough that adapters and interfaces can
grow on top of it.

## Product Thesis

Agent Bus should be the messaging layer for distributed AI agents:

- runtime-agnostic,
- cross-machine and cross-device,
- durable by default,
- CLI-first,
- easy to self-host,
- clear about the boundary between relay, adapter, and workflow.

The current priority is to stabilize durable messaging and Worker Adapter
patterns. A tray app, desktop console, and richer status surface become useful
after the protocol and local runtime boundary are dependable.

## v0.x: Reliable Messaging Layer

Focus: make the relay boring, observable, and recoverable.

Expected work:

- Keep the FastAPI + SQLite + SSE core simple and single-node.
- Preserve handler-success ACK semantics.
- Maintain pending, failed, and un-ACKed inspection.
- Maintain explicit failed-event requeue and cumulative attempt/error evidence.
- Keep idempotency guidance centered on event `id` and application-owned
  `payload.task_id`.
- Improve CLI diagnostics for URL, token, auth scope, health, send, pending,
  ACK, and listener behavior.
- Keep payloads flexible while documenting a recommended task envelope.

Acceptance criteria:

- A new agent endpoint can prove `send -> pending -> handler success -> ACK ->
  pending empty`.
- Repeated failed handlers accumulate attempts across listener processes, become
  terminal at the configured threshold, and remain explicitly inspectable and
  requeueable by the recipient.
- A disconnected listener can reconnect without losing assigned work.
- Operators can distinguish service failure, network failure, token failure,
  and local handler failure.

## v0.x: Worker Runtime / Adapter Examples

Focus: show how runtimes integrate without moving execution into Agent Bus.

Expected work:

- Keep `docs/worker.md` as the adapter boundary.
- Maintain one generic shell/script adapter example.
- Maintain one concrete OpenCode adapter example.
- Add examples only when they demonstrate a reusable integration pattern.
- Document safe handler templates and payload passing.
- Make adapter examples explicit about local ownership of workspace, Git, test,
  prompt, retry, and reporting behavior.

Non-goals:

- No built-in OpenCode, Codex, Claude Code, or Hermes executor.
- No server-side task execution.
- No built-in Git operations or PR creation.

## v0.x: Security And Deployment Boundary

Focus: make self-hosting safe enough for a trusted personal or small-team
network.

Expected work:

- Keep per-agent bearer tokens as the default exposed-deployment model.
- Keep shared token support limited to local development and migration.
- Document Tailscale/private-network deployment as the simplest safe default.
- Document HTTPS/tunnel/reverse-proxy options without making them required for
  local use.
- Preserve agent-scoped send, stream, and ACK checks.
- Add operational guidance for rotating tokens and preserving the SQLite DB.

Acceptance criteria:

- Public plaintext bearer-token deployment is clearly discouraged.
- Tailscale-only and localhost deployments have clear setup and verification
  paths.
- Deployment docs protect existing tokens and durable event data.

## v0.x: CLI Usability

Focus: keep the developer-first path simple before adding a heavier UI.

Current CLI operation is appropriate for early adopters, but daily use should
become less brittle:

- one documented setup path for a new endpoint,
- one command to run a configured listener,
- one diagnostic command for URL, token, health, auth scope, send, pending, and
  ACK,
- clearer error messages for network, token, service, listener, and handler
  failures,
- examples that show adapter behavior without assuming one runtime.

This phase should improve operator confidence without introducing a complex Web
UI.

## v1.0: Lightweight Console / Tray App

Focus: make daily operation approachable without turning Agent Bus into a heavy
web platform.

Possible shape:

- A small local desktop or tray app, similar in spirit to Clash or CC Switch.
- One-click local listener start / stop.
- Endpoint profile management.
- Token configuration and validation.
- Worker online / offline status.
- Recent events and pending tasks.
- Basic logs and failure summaries.

This should remain an operator surface for the relay and local adapters. It
should not become the place where workflows, prompts, model routing, memory, or
Git policy are designed.

## v1.x: Richer Status, Logs, Notifications

Focus: improve operational visibility after the relay and UI shell are stable.

Possible work:

- Worker heartbeat / presence.
- Task status conventions beyond raw event types.
- Retry hints and richer failure summaries beyond the current durable attempt
  count, last error, terminal failed state, and explicit requeue.
- Optional dead-letter routing beyond the current recipient-held failed state.
- Structured adapter logs.
- Human notifications through local desktop, CLI, webhook, Telegram, or other
  optional clients.

These features should remain messaging and observability features. They should
not force a single workflow model.

## Competition And Strategic Risks

Official AI platforms may add remote-agent or remote-worker features. Agent Bus
should not try to out-platform them. Its defensible path is to stay useful where
official products are least likely to be neutral:

- heterogeneous runtime collaboration,
- personal and small-team self-hosting,
- private-network operation,
- CLI-first recovery,
- adapters that do not require one vendor ecosystem.

The project should actively avoid three failure modes:

- becoming so broad that it stops solving one sharp problem,
- adding UI before messaging reliability is proven,
- becoming a workflow engine instead of a messaging layer.

## Later: Pluggable Runtime Adapters

Focus: make integration easier while preserving the core boundary.

Possible adapters:

- OpenCode,
- Codex CLI,
- Claude Code,
- shell scripts,
- GitHub Actions,
- NAS / homelab jobs,
- mobile notification or approval clients.

Adapter packaging can become more systematic over time, but adapter execution
should remain outside the Agent Bus server. A plugin system is acceptable only
if it keeps the relay runtime-agnostic.

## Explicit Non-Roadmap

Agent Bus should not spend early product energy on:

- a complex Web UI,
- workflow DAGs,
- model routing,
- prompt management,
- memory databases,
- GitHub project replacement,
- enterprise multi-tenant IAM,
- clustering before single-node reliability is exhausted.

## Current Product Decision

Near term, Agent Bus should make durable messaging and Worker Adapter examples
stable. UI, tray app, richer worker state, retry dashboards, and plugin-style
runtime adapters are valuable later, but they depend on the core relay boundary
staying small and reliable.
