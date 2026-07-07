# Codex / OpenCode Review Loop Example

This example shows the smallest useful closed loop on top of Agent Bus:

```text
Mac sender -> task:new -> Windows adapter / OpenCode -> task:completed -> Mac review listener
```

Agent Bus remains only the durable relay: event storage, pending inspection,
ACK, replay, SSE / polling, and auth. Git operations, OpenCode invocation,
Codex review, local workdir selection, prompt shaping, and review policy all
stay in endpoint adapters.

## Files

- `payload-task-new.json` is a sample `task:new` payload.
- `windows-worker.ps1` wraps the shared Windows polling adapter with a static
  local `-Workdir` and an OpenCode command.
- `mac-review-listener.sh` polls for result events. It runs the local review
  placeholder for `task:completed`, logs and ACKs `task:failed`, and never runs
  the review script for failed tasks.

## Event Shape

`task:new` payload:

```json
{
  "task_id": "review-loop-demo-001",
  "title": "Make a small change and report back",
  "prompt": "Inspect the repo, make the smallest safe change, run checks, and summarize the result.",
  "repo": "atongrun/agent-bus",
  "branch": "codex/example-task",
  "requester": "mac-codex"
}
```

`task:completed` payload:

```json
{
  "task_id": "review-loop-demo-001",
  "status": "completed",
  "summary": "Command exited 0",
  "artifact_uri": "",
  "repo": "atongrun/agent-bus",
  "branch": "codex/example-task"
}
```

`task:failed` payload:

```json
{
  "task_id": "review-loop-demo-001",
  "status": "failed",
  "error": "Command exited 1",
  "exit_code": 1,
  "repo": "atongrun/agent-bus",
  "branch": "codex/example-task"
}
```

These are conventions, not server-enforced schemas.

## Result Event Delivery

Result events are at-least-once. The Windows adapter sends `task:completed`
before ACKing the original `task:new` event. If that ACK fails, the original
`task:new` remains replayable and the adapter may emit another `task:completed`
for the same work on the next pass.

`task:failed` can also repeat while the original `task:new` remains unacked for
inspection or replay. Consumers should treat `payload.task_id` as the
idempotency key for both completed and failed results.

The Mac review listener handles both terminal result types: it runs review only
for `task:completed`, logs `task_id`, `error`, and `exit_code` for `task:failed`,
and ACKs each result event after its local handling succeeds.

## Mac Sender And Review Listener

Set the Mac-side identity. The same agent can send the task and receive the
completion event.

```bash
export AGENT_BUS_URL=http://<vps-tailscale-ip>:8800
export AGENT_BUS_TOKEN=<mac-codex-token>
export AGENT_BUS_AGENT=mac-codex
```

Start the review listener before dispatching work:

```bash
bash ./examples/workflows/codex-opencode-review-loop/mac-review-listener.sh
```

By default, the listener only prints a placeholder review message. To plug in a
real local script, set `AGENT_BUS_REVIEW_SCRIPT`; the script receives a path to a
JSON file containing the `task:completed` payload.

```bash
export AGENT_BUS_REVIEW_SCRIPT=/absolute/path/to/review.sh
bash ./examples/workflows/codex-opencode-review-loop/mac-review-listener.sh
```

A future wrapper can replace that review script with `codex review` or
`codex exec`. Do not put Codex-specific review decisions in Agent Bus core.

Send a task:

```bash
agent-bus send \
  --from mac-codex \
  --to windows-opencode \
  --type task:new \
  --payload-file examples/workflows/codex-opencode-review-loop/payload-task-new.json
```

## Windows Worker Adapter

On Windows, set the worker identity and run the adapter with a static local
workdir:

```powershell
$env:AGENT_BUS_URL = "http://<vps-tailscale-ip>:8800"
$env:AGENT_BUS_TOKEN = "<windows-opencode-token>"
$env:AGENT_BUS_AGENT = "windows-opencode"

.\examples\workflows\codex-opencode-review-loop\windows-worker.ps1 `
  -Workdir "D:\projects\agent-bus" `
  -ReviewerAgent "mac-codex"
```

The adapter receives `task:new`, runs:

```text
opencode run --prompt <payload.prompt>
```

If the command exits `0`, it sends `task:completed` to `payload.requester`,
`-ReviewerAgent`, or the original event sender, then ACKs the original event. If
the command fails, it sends `task:failed` and leaves the original event unacked
for replay/inspection.

`-Workdir` is local static configuration. Do not trust an absolute workdir from
remote payload. A future `payload.repo` to local path mapping should be a local
allowlist owned by the Windows adapter.

## Deliberate Non-Goals

- No server protocol changes.
- No schema enforcement.
- No GUI or tray app.
- No automatic merge.
- No repo/workdir whitelist routing yet.
- No built-in Codex or OpenCode roles in Agent Bus core.
