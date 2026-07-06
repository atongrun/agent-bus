# Agent Bus Vision

Agent Bus is a lightweight, runtime-agnostic messaging layer for distributed AI
agents.

It starts as a small durable event relay, and it should remain grounded in that
role as the product grows. Its job is to let agents, scripts, and local
automation endpoints communicate across machines and runtimes without forcing
them into one vendor ecosystem, one IDE, one workflow engine, or one always-on
desktop application.

## North Star

Distributed AI work increasingly spans heterogeneous endpoints:

- Codex on a Mac,
- OpenCode on Windows,
- Claude Code or scripts on Linux,
- a VPS relay,
- NAS or homelab jobs,
- GitHub Actions,
- notification or approval clients on other devices.

Agent Bus should make that network reliable through a small shared transport:
durable events, ACK, replay, reconnect, role or endpoint addressing, CLI
inspection, and self-hosted deployment.

## Near-Term Positioning

In v0.x, Agent Bus is a reliable event relay. It should make the following loop
boring:

```text
send -> persist -> deliver -> handler succeeds -> ACK -> pending empty
```

The goal is not millisecond latency. Normal delivery should happen within about
one second, and the more important property is that failed, offline, or
interrupted work is not silently lost.

## Mid-Term Positioning

The mid-term product should make heterogeneous agent work:

- recoverable after crashes and disconnects,
- inspectable from a CLI,
- easy to run on localhost, a VPS, a NAS, or a private LAN,
- easy to connect to local Worker Runtimes / adapters,
- safe enough for trusted personal or small-team networks.

Worker Runtime examples can grow around Agent Bus, but execution remains
outside the relay. A Worker Runtime may call OpenCode, Codex CLI, Claude Code,
a shell script, GitHub Actions, or a local program. Agent Bus only sees events.

## Long-Term Positioning

The long-term vision is not a workflow platform. It is a durable messaging
substrate for distributed AI agents.

Later product layers may include:

- a lightweight console, tray app, or desktop app,
- worker presence and task status,
- logs, retry state, and notifications,
- endpoint profiles and token management,
- plugin-style runtime adapters.

Those layers should sit on top of the relay boundary. They should not move Git
operations, AI execution, prompt management, memory, DAG scheduling, or workflow
policy into the Agent Bus core.

## Principles

- Runtime-agnostic by default.
- Messaging layer, not workflow engine.
- Robustness before complexity.
- Recoverability before flashy real-time behavior.
- Second-level responsiveness is enough; lower latency is welcome but not the
  primary goal.
- CLI-first before UI-heavy.
- Easy self-hosting before platform features.
- Security boundary first: localhost, private network, HTTPS, tunnel, or
  equivalent trusted transport.

## Non-Goals

Agent Bus should not implement:

- built-in Codex, OpenCode, Claude Code, Hermes, or GitHub Actions behavior,
- server-side task execution,
- Git clone / branch / commit / push / PR operations,
- prompt construction or model routing,
- shared memory or context management,
- workflow DAGs,
- planner / worker / reviewer as hardcoded identities,
- enterprise multi-tenant IAM,
- a large Web UI before the CLI and relay are stable.

Planner, worker, reviewer, architect, coder, and notifier are workflow roles.
They are not Agent Bus primitives.

## Roadmap

The detailed roadmap lives in [roadmap.md](roadmap.md). The current product
decision is:

- v0.x: stabilize durable messaging, ACK, replay, diagnostics, security, and
  Worker Adapter examples.
- v1.0: consider a lightweight console, tray app, or desktop app for daily
  operation.
- v1.x: add worker status, task status, logs, retry state, and notifications.
- Later: make runtime adapters easier to package without turning the relay into
  a workflow engine.
