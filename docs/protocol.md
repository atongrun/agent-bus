# Agent Bus Event Protocol v0.2

All communication is JSON over HTTP. The service exposes event creation,
pending and failed inspection, ACK, failure recording, explicit requeue, and SSE
streaming endpoints.

## Authentication

Authenticated endpoints require:

```text
Authorization: Bearer <AGENT_BUS_TOKEN>
```

Recommended server configuration:

```text
AGENT_BUS_AGENT_TOKENS=architect=<token>,coder=<token>
```

Legacy shared-token mode is still accepted when only `AGENT_BUS_TOKEN` is set.

## Create Event

`POST /events`

```json
{
  "from_agent": "architect",
  "to_agent": "coder",
  "type": "task:new",
  "payload": {
    "task_id": "task-001",
    "title": "Implement the issue",
    "prompt": "Implement, test, and open a PR."
  }
}
```

In per-agent token mode, `from_agent` must match the token owner.

Response `201 Created` returns the event:

```json
{
  "id": 1,
  "from_agent": "architect",
  "to_agent": "coder",
  "type": "task:new",
  "payload": {"task_id": "task-001"},
  "status": "pending",
  "created_at": "2026-07-04 12:00:00",
  "delivered_at": null,
  "acked_at": null,
  "retry_count": 0,
  "last_error": null
}
```

## List Pending Events

`GET /events/pending?agent=<agent_name>`

Returns all un-ACKed events for the agent. In per-agent token mode, the token
must belong to the requested agent.

## Stream Events

`GET /events/stream?agent=<agent_name>`

The server first replays all pending or delivered events, then streams new
events. The CLI uses the Authorization header. The `token` query parameter is
kept only as a fallback for clients that cannot set headers.

SSE frame:

```text
id: <event_id>
event: message
data: <json encoded event>

```

## ACK Event

`POST /events/{id}/ack`

ACK means the recipient has successfully processed the event. A listener should
ACK only after its handler exits successfully. If handling fails, times out, or
the listener exits before ACK, the event remains replayable.

In per-agent token mode, only the recipient agent may ACK the event. Listeners
also send `expected_retry_count=<count observed in the delivered event>` as a
query parameter. If another failure changed that count before ACK, the server
returns `409` rather than letting a stale ACK overwrite newer evidence. Manual
ACK may omit the precondition. Repeating ACK after the event is already ACKed is
idempotent.

## Record a Failed Attempt

`POST /events/{id}/fail`

```json
{
  "error": "Handler failed",
  "max_attempts": 3,
  "expected_retry_count": 1
}
```

The recipient reports every unsuccessful handler attempt. In one SQLite
transaction the server checks `expected_retry_count`, increments `retry_count`,
updates `last_error`, and either returns the event to `pending` or moves it to
terminal `failed` when the threshold is reached.

The observed retry count is an optimistic precondition, not a protocol
idempotency key. Repeating the same report after the count has advanced returns
the current event state with `"attempt_recorded": false` and does not increment
again. Repeating a report after terminal failure is likewise idempotent. An
ACKed event returns `409`.

For rolling-upgrade compatibility, an older client may omit
`expected_retry_count` and send only `error`. Older listeners called `/fail` only
after exhausting their process-local threshold, so this legacy shape performs
one atomic terminal transition. Current listeners always send the observed count
and use the durable server-side threshold.

## List Failed Events

`GET /events/failed?agent=<agent_name>`

Returns terminal failed events for the agent, including cumulative
`retry_count` and `last_error`. In per-agent token mode, the token must belong to
the requested agent.

## Requeue a Failed Event

`POST /events/{id}/requeue`

Only the recipient may requeue the event. `failed` transitions to `pending`,
clearing the delivery timestamp while preserving `retry_count` and `last_error`
as recovery evidence. Requeue is idempotent while the event remains pending.
Delivered and ACKed events return `409`.

## Recommended Event Types

The event types below are **conventions, not a required schema**. The server
never validates payload structure. Direction labels use `sender → receiver` as
a workflow convention — any agent can play either role depending on the exchange.

| Type | Typical direction | Suggested payload |
|------|-------------------|-------------------|
| `task:new` | sender → receiver | `task_id`, `title`, `prompt`, `repo`, `branch`, `url` |
| `task:accept` | receiver → sender | `task_id`, `message` |
| `task:failed` | receiver → sender | `task_id`, `exit_code`, `summary` |
| `pr:ready` | receiver → sender | `task_id`, `pr_url`, `summary` |
| `review:done` | sender → receiver | `task_id`, `status`, `summary` |

Payloads are free-form JSON. `pr:ready` is a GitHub coding workflow example;
for non-GitHub workflows, `task:completed` with `artifact_uri` is a reasonable
alternative. Add custom types (`deploy:done`, `test:passed`, etc.) at any time.

## Status Values

| Status | Meaning |
| --- | --- |
| `pending` | Awaiting delivery, including after a non-terminal failed attempt or explicit requeue |
| `delivered` | Sent over SSE but not ACKed |
| `acked` | Successfully processed by recipient |
| `failed` | Terminal handler failure; held from delivery until recipient requeue |

## State Transitions

| Current state | ACK | Record failed attempt | Requeue |
| --- | --- | --- | --- |
| `pending` | `acked` | `pending`, or `failed` at threshold | idempotent `pending` |
| `delivered` | `acked` | `pending`, or `failed` at threshold | `409` |
| `failed` | `409` | idempotent `failed` | `pending` |
| `acked` | idempotent `acked` | `409` | `409` |

Each transition is decided atomically in SQLite. Delivery remains at least once;
the protocol does not provide exactly-once execution, claims, leases, or
competing-consumer coordination.

## Error Codes

- `401`: missing or invalid token
- `403`: token is valid but not authorized for the requested agent/event
- `404`: event not found
- `409`: state transition conflicts with the event's current state or observed attempt
- `422`: request validation error
