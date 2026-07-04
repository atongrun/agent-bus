# Agent Bus Event Protocol v0.2

All communication is JSON over HTTP. The service exposes event creation,
pending inspection, ACK, and SSE streaming endpoints.

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
  "retry_count": 0
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

In per-agent token mode, only the recipient agent may ACK the event.

## Recommended Event Types

| Type | Direction | Suggested payload |
| --- | --- | --- |
| `task:new` | architect -> coder | `task_id`, `title`, `prompt`, `repo`, `branch`, `url` |
| `task:accept` | coder -> architect | `task_id`, `message` |
| `task:failed` | coder -> architect | `task_id`, `exit_code`, `summary` |
| `pr:ready` | coder -> architect | `task_id`, `pr_url`, `summary` |
| `review:done` | architect -> coder | `task_id`, `status`, `summary` |

Payloads remain free-form JSON objects. These fields are conventions for
interoperability, not strict server-side validation.

## Status Values

| Status | Meaning |
| --- | --- |
| `pending` | Created and not yet delivered |
| `delivered` | Sent over SSE but not ACKed |
| `acked` | Successfully processed by recipient |
| `failed` | Reserved for future retry policy |

## Error Codes

- `401`: missing or invalid token
- `403`: token is valid but not authorized for the requested agent/event
- `404`: event not found
- `409`: event cannot be ACKed
- `422`: request validation error
