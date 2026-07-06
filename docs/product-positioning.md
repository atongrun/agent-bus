# Product Positioning

Agent Bus is a lightweight, runtime-agnostic messaging layer for distributed AI
agents.

It exists for agent networks that do not live inside one IDE, one vendor
runtime, one machine, or one orchestration framework. A sender may be Codex on a
Mac, the receiver may be OpenCode on Windows, a follow-up notifier may be a
shell script on a VPS, and a future reviewer may be Claude Code, GitHub Actions,
or another local tool. Agent Bus should give those endpoints one durable event
transport without making any of them the center of the system.

## What Agent Bus Is

- A durable event relay for agent-to-agent communication.
- A small self-hosted service that can run on localhost, a VPS, a NAS, or a
  private network.
- A CLI-first integration layer for heterogeneous runtimes.
- A role-addressed event transport with explicit ACK and replay behavior.
- A foundation for local Worker Runtime / adapter examples that execute work
  outside the relay.

The core product value is not that an agent can send an HTTP request. The value
is that distributed agents can exchange recoverable work items through a
minimal shared protocol:

- events are persisted before delivery,
- recipients ACK after successful handling,
- un-ACKed work can replay after reconnect,
- endpoints can be addressed by role or agent name,
- humans and scripts can inspect pending work from the CLI,
- deployment remains easy enough for one person to self-host.

## What Agent Bus Is Not

Agent Bus should not become:

- a workflow engine,
- a DAG scheduler,
- an AI model gateway,
- a prompt-management system,
- a memory or context database,
- a GitHub issue / pull request replacement,
- a vendor-specific bridge for Codex, OpenCode, Claude Code, or Hermes,
- a desktop control plane before the messaging layer is boring and reliable.

Planner, worker, reviewer, architect, coder, and notifier are workflow labels.
They are not built-in identities. Hermes, Codex, OpenCode, Claude Code, GitHub
Actions, shell scripts, and future tools are clients or adapters. None of them
should be treated as the system center.

## Why Distributed AI Agents Need This

Many agent systems optimize for coordination inside one runtime: one IDE, one
CLI, one hosted product, or one vendor ecosystem. That does not cover the
practical shape of a personal or small-team agent network:

- a Mac runs planning and review agents,
- a Windows machine runs a tool that works best there,
- a VPS provides always-on relay and notification services,
- a NAS or local server runs scripts,
- GitHub Actions runs CI or scheduled automation,
- future devices may only need status, approval, or notification.

Those endpoints need a communication layer with a smaller contract than a
workflow engine and stronger reliability than ad hoc HTTP callbacks. Agent Bus
fills that gap by making cross-machine handoff explicit, durable, inspectable,
and recoverable.

## Comparison With Adjacent Tools

| Alternative | What it is good at | Why Agent Bus is different |
| --- | --- | --- |
| Raw HTTP | Simple one-shot calls | HTTP does not define durable event storage, ACK, replay, pending inspection, or agent addressing. |
| Webhooks | Notifications between services | Webhooks assume receiver availability and usually push delivery complexity to each integration. |
| Git polling | Code and task state through repository changes | Git is auditable but slow and indirect for live handoff, listener status, ACK, retry, and reconnect. |
| Redis Pub/Sub | Fast transient broadcast | Plain Pub/Sub is not durable; subscribers can miss messages while offline. |
| Redis Streams | Durable stream primitive | Useful infrastructure, but Agent Bus offers an agent-facing protocol, CLI, auth stance, and self-hosted defaults. |
| MQTT | Lightweight device messaging | Strong fit for IoT-style topics, but less tailored to agent task handoff, handler-success ACK, and CLI-first recovery. |
| NATS / JetStream | Production-grade messaging | More capable and operationally heavier; Agent Bus should borrow reliability patterns without requiring that stack early. |
| Workflow engines | DAGs, retries, state machines | Agent Bus should stop below this layer. Workflows can use Agent Bus; they should not live inside the core. |

## Product Boundary

The boundary is:

```text
Agent Bus core:
  event API, persistence, ACK, replay, addressing, auth, CLI inspection

Worker Runtime / adapter:
  local tool invocation, workspace setup, Git operations, tests, PR creation,
  runtime-specific prompts, logs, task-specific retry policy

Workflow layer:
  planning strategy, reviewer policy, task decomposition, human approvals,
  DAGs, model selection, memory/context decisions
```

Agent Bus can document adapter patterns and ship small examples, but the server
should remain a runtime-agnostic messaging layer.

## Competition And Risk

Official agent platforms may eventually offer remote agents, remote workers, or
hosted task handoff. Those systems will likely be strongest inside their own
ecosystems first: one vendor runtime, one IDE, one cloud platform, or one
hosted workflow model.

Agent Bus has a different opportunity:

- heterogeneous runtimes,
- cross-device and cross-machine operation,
- self-hosting,
- private-network deployment,
- CLI-first recovery,
- small trusted agent networks.

The main product risks are:

- positioning too broadly and becoming an unfocused platform,
- adding UI before the relay is operationally boring,
- adding workflow-engine behavior before adapter patterns are stable,
- binding the project too tightly to the first Codex / OpenCode use case,
- hiding execution policy inside the server instead of keeping it in adapters.

The mitigation is to keep the core contract narrow: event transport,
persistence, ACK, replay, addressing, auth, and inspection.

## Positioning Statement

Agent Bus is the small durable transport that lets heterogeneous AI agents and
automation scripts coordinate across machines without agreeing on one runtime,
one vendor, or one workflow engine.
