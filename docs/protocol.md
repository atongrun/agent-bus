# Agent Bus — Event Protocol v0.1

## Wire Format

All communication is JSON over HTTP. The server exposes a REST API for event creation and acknowledgement, and an SSE endpoint for event delivery.

### Authentication

All endpoints except `/health` require:

```
Authorization: Bearer <AGENT_BUS_TOKEN>
```

The token is configured server-side via `AGENT_BUS_TOKEN` environment variable.

### Content Type

- Request: `application/json`
- Response: `application/json`
- SSE: `text/event-stream`

---

## 1. Create Event

**`POST /events`**

Request body:
```json
{
  "from_agent": "architect",
  "to_agent": "coder",
  "type": "task:new",
  "payload": {
    "url": "https://github.com/xxx/issues/12",
    "task_id": "issue-12"
  }
}
```

Fields:
- `from_agent` (string, required): Sender agent name
- `to_agent` (string, required): Recipient agent name
- `type` (string, required): Event type (see below)
- `payload` (object, required): Arbitrary JSON payload

Response `201 Created`:
```json
{
  "id": 1,
  "from_agent": "architect",
  "to_agent": "coder",
  "type": "task:new",
  "payload": {"url": "...", "task_id": "issue-12"},
  "status": "pending",
  "created_at": "2026-07-02T12:00:00Z",
  "delivered_at": null,
  "acked_at": null,
  "retry_count": 0
}
```

Response `422 Unprocessable Entity`: Validation error details.

---

## 2. Stream Events (SSE)

**`GET /events/stream?agent=<agent_name>`**

Establishes a Server-Sent Events connection. The server first replays all un-ACKed events for the agent (status `pending` or `delivered`), then sends new events in real-time.

Query parameters:
- `agent` (string, required): The agent name to receive events for.

SSE event format:
```
id: <event_id>
event: message
data: <json encoded event object>

```

The JSON `data` field contains the full event object (same schema as create response).

On first connect, all un-ACKed events are replayed in order of `created_at`.

New events are pushed as they are created (via polling in v0.1).

Connection drops are handled by the client reconnecting — on reconnect, un-ACKed events are replayed.

---

## 3. Acknowledge Event

**`POST /events/{id}/ack`**

Marks an event as processed. The event ID is obtained from the SSE stream or event creation response.

Response `200 OK`:
```json
{
  "id": 1,
  "status": "acked",
  "acked_at": "2026-07-02T12:05:00Z"
}
```

Once ACKed, the event will not be replayed on future SSE connections.

Response `404 Not Found`: Event does not exist.
Response `409 Conflict`: Event already ACKed (idempotent — still returns 200 in v0.1).

---

## 4. Health Check

**`GET /health`**

No authentication required.

Response `200 OK`:
```json
{
  "status": "ok",
  "timestamp": "2026-07-02T12:00:00Z"
}
```

---

## Event Schema

```json
{
  "id": 1,
  "from_agent": "architect",
  "to_agent": "coder",
  "type": "task:new",
  "payload": {},
  "status": "pending",
  "created_at": "2026-07-02T12:00:00Z",
  "delivered_at": "2026-07-02T12:00:01Z",
  "acked_at": null,
  "retry_count": 1
}
```

### Status Values

| Status    | Meaning                                           |
|-----------|---------------------------------------------------|
| `pending` | Created, not yet delivered to recipient           |
| `delivered` | Sent to recipient via SSE, not yet ACKed        |
| `acked`   | Recipient has acknowledged processing             |
| `failed`  | Reserved for future use (delivery retry exhausted)|

### Event Types (v0.1)

| Type          | Typical Direction    | Payload (suggested)                    |
|---------------|----------------------|----------------------------------------|
| `task:new`    | architect → coder    | `url`, `task_id`, `title`              |
| `task:accept` | coder → architect    | `task_id`                              |
| `pr:ready`    | coder → architect    | `url`, `pr_number`, `task_id`          |
| `review:done` | architect → coder    | `url`, `task_id`, `status`             |

Payload is free-form JSON. These are conventions, not enforced by the server.

---

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Human-readable error message"
}
```

HTTP status codes used:
- `400` — Bad request (malformed input)
- `401` — Missing or invalid token
- `404` — Event not found
- `409` — Conflict (e.g., already ACKed)
- `422` — Validation error
- `500` — Internal server error

---

## Client Behavior

### Sending Events

1. POST to `/events` with event body.
2. On success, note the returned event ID.
3. On failure, retry with exponential backoff (not implemented in v0.1 client).

### Receiving Events

1. Connect to SSE at `/events/stream?agent=<name>`.
2. Process each received event.
3. After processing, POST to `/events/{id}/ack`.
4. If processing fails, do NOT ACK — it will be replayed on reconnect.
5. On connection drop, reconnect (SSE clients typically auto-reconnect).

### Idempotency

Clients should be prepared to receive the same event more than once (in crash/reconnect scenarios). Use the event `id` field for deduplication.
