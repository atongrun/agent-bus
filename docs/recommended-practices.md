# Agent Bus Recommended Practices

Agent Bus should stay small while borrowing the reliability habits of mature
queue and agent systems. The current target is not a general workflow platform;
it is a reliable handoff path for a small trusted agent network.

## Recommended Architecture

For v0.2 and v0.2.x, keep the core stack:

- FastAPI HTTP API for event creation, inspection, and ACK.
- SQLite for durable storage.
- SSE for recipient-side delivery.
- CLI listeners for Mac, Windows, and localhost agents.
- Per-agent bearer tokens over a private transport such as Tailscale.

This matches the project's operational goals: light deployment, second-level
latency, simple recovery, and low maintenance. Do not add RabbitMQ, Redis,
NATS, Temporal, OAuth, mTLS, or a dashboard until the simple relay has a real
operational need for them.

## Reliability Rules

Use these queue-style rules as the baseline:

- Persist an event before delivery.
- ACK only after successful handling.
- Treat delivery as at-least-once, not exactly-once.
- Make handlers idempotent by using `id` or `payload.task_id`.
- Keep un-ACKed events inspectable and replayable.
- Inspect terminal failures with `agent-bus failed` and require an explicit
  recipient `requeue` before redelivery.
- Prefer explicit failure events over silently swallowing handler errors.

The current server persists attempt counts and last errors across listener
processes, then holds repeatedly failing work in terminal `failed`. Keep that
simple explicit recovery model until real multi-consumer load requires a
different coordination design.

## Client Experience Rules

The client path should be boring:

- A new machine should have one documented setup path.
- A configured machine should have one command to run the local CLI.
- A single diagnostic command should check URL, token, health, auth, send,
  pending, and ACK.
- Troubleshooting should distinguish service failure, private-network failure,
  token failure, listener failure, and Codex sandbox network false negatives.

The near-term improvement is a `doctor` command or local wrapper script. This is
more important than adding a richer protocol surface.

## Current Production Topology

The recommended first deployment is a private-network relay between trusted
machines:

```text
Mac client -> VPS Agent Bus over Tailscale -> Windows receiver
```

The VPS should answer on its Tailscale address. Public `8800/tcp` does not need
to be reachable and should normally stay closed. A failed public-IP check is not
a failure when the Tailscale URL works.

## Future Protocol Shape

Keep free-form payloads for now, but gradually converge on a task envelope:

- `task_id`
- `title`
- `prompt`
- `repo`
- `branch`
- `status`
- `attempt`
- `last_error`
- `deadline`

Do not enforce this application envelope in v0.2.x. Agent Bus Core uses its
server event ID and persisted retry count for delivery recovery; application
deduplication remains the handler's responsibility.

## What Not To Do Yet

- Do not replace SQLite with a queue service just to feel more standard.
- Do not add orchestration before reliable handoff is effortless.
- Do not expose bearer-token HTTP on the public internet.
- Do not use public-IP reachability as the readiness check for a Tailscale-only
  deployment.
- Do not optimize for millisecond latency before operator recovery is boring.
