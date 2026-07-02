# Agent Bus — Design Document

## Motivation

Two AI agents running on separate machines (Mac and Windows) collaborate via GitHub issues and PRs. The architect agent (Codex on Mac) creates tasks; the engineer agent (OpenCode on Windows) implements them. Today, there is no automated event notification between them — when one agent finishes work, a human must manually notify the other.

Agent Bus provides a lightweight, reliable event relay so agents can signal each other directly.

## Design Goals

1. **Simplicity first**: Python + FastAPI + SQLite. One binary to deploy.
2. **Durability over real-time**: Events are persisted before they're delivered. No message loss.
3. **At-least-once delivery**: Events remain until explicitly acknowledged (ACK).
4. **Offline resilience**: If an agent is offline, events queue up and are delivered on reconnect.
5. **Minimal operational burden**: systemd service, SQLite (no separate DB server), single token auth.

## Architecture Decisions

### Why SSE instead of WebSocket?

| Factor        | SSE                        | WebSocket                      |
|---------------|----------------------------|--------------------------------|
| Complexity    | Lower — unidirectional     | Higher — bidirectional         |
| Reconnection  | Built-in (EventSource)     | Manual                         |
| Proxy friendly| Yes (plain HTTP)           | Sometimes problematic          |
| For this use case | Perfect fit — server→client push only | Overkill |

Clients send events via HTTP POST (not SSE), so bidirectional WebSocket isn't needed. SSE gives us simple, auto-reconnecting push from server to client.

### Why SQLite instead of Redis/Postgres?

- Zero setup — embedded, no separate daemon.
- Single VPS deployment — no need for distributed coordination.
- WAL mode gives concurrent read/write performance.
- For two clients handling ~hundreds of events/day, SQLite is more than sufficient.

### Event Lifecycle

```
[Client A] --POST /events--> [Server: status=pending]
                                  |
                           [SSE push to Client B]
                                  |
                    [Client B receives event, status=delivered]
                                  |
                    [Client B POST /events/{id}/ack]
                                  |
                           [status=acked, removed from queue]
```

If Client B is offline when the event is created:
- Event stays `pending` in SQLite.
- When Client B connects to SSE, all `pending` + `delivered` events for that agent are replayed.
- Client B ACKs events it has processed.
- On next reconnect, only un-ACKed events are replayed.

### Auth Model

Single shared bearer token for simplicity. All clients use the same token. This is appropriate for a small trusted team. Future versions can add per-agent tokens or API keys.

## Trade-offs

| Decision                    | Benefit                          | Cost                                |
|-----------------------------|----------------------------------|-------------------------------------|
| Single shared token         | Simple to configure              | No per-agent access control         |
| SQLite                      | Zero-ops database                | Not suitable for high concurrency   |
| SSE over WebSocket          | Simpler, auto-reconnect           | Slightly higher latency per event   |
| No message encryption       | Simple                            | Trusts VPS operator                 |
| At-least-once (no dedup)    | Simple                            | Duplicates possible on crash-reconnect |
| Polling-based SSE loop      | Works with any HTTP client        | Slight delay for new events (500ms) |

## Future Extensions (v0.2+)

- Per-agent tokens and access control
- Event type filtering in SSE stream
- Client-side handler hooks (`--on task:new "command {payload.foo}"`)
- Retry with backoff for failed deliveries
- Web UI dashboard
- GitHub App integration (auto-detect events from issue/PR activity)
