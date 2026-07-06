# Worker Runtime / Worker Adapter

## What It Is

A **Worker Runtime** (or Worker Adapter) is a thin shell that sits between Agent
Bus and whatever local tool executes the actual work. It is not part of Agent
Bus. It is an example of what an endpoint can do, not a required component.

```
Agent Bus            Worker Runtime                 Local Tool
─────────            ──────────────                 ──────────
                     ┌──────────────────────┐
SSE  ──task:new──▶   │ 1. Receive event     │
                     │ 2. Decide if relevant │
                     │ 3. Prepare workspace  │──▶ git clone / checkout / pull
                     │ 4. Invoke tool        │──▶ opencode run / claude --print
                     │ 5. Collect result     │◀── exit code + output
                     │ 6. Report back        │──▶ agent-bus send task:completed
                     └──────────────────────┘
```

The Worker Runtime talks to Agent Bus over the same HTTP/SSE protocol every
other client uses. Agent Bus has no idea what happens inside the Worker
Runtime — it only sees events go out (`task:new`) and events come back
(`task:completed`, `pr:ready`, `task:failed`).

## Why It Is NOT Part of Agent Bus

| Concern | Agent Bus handles | Worker Runtime handles |
|---------|:-----------------:|:----------------------:|
| Event transport | ✅ | — |
| Git clone / checkout / pull | — | ✅ |
| AI execution (OpenCode, Claude, etc.) | — | ✅ |
| Test running | — | ✅ |
| Commit / push / PR creation | — | ✅ |
| Prompt construction | — | ✅ |
| Workspace management | — | ✅ |
| Retry / timeout / error handling | — | ✅ |
| ACK semantics | ✅ (protocol) | ✅ (when to ACK) |

If Agent Bus baked in Git, AI execution, or workflow logic, it would stop being
a relay and become an opinionated platform. The relay stays small and
runtime-agnostic **because** all of the execution concern lives in the Worker
Runtime.

## Planner / Worker / Reviewer Are Roles, Not Components

Agent Bus does not hardcode `planner`, `worker`, or `reviewer` as system
identities. These are **role labels** that a workflow adopts for readability.
Any agent can send events. Any agent can receive them. The direction of a
particular event type (`task:new` goes sender → receiver, `pr:ready` goes
receiver → sender) is a workflow convention, not a protocol constraint.

```text
# Agent A sends a task to Agent B — A is the "planner" in this moment
agent-bus send --to agent-b --type task:new --payload '{...}'

# Agent B responds with a PR — B is the "worker" who did the work
agent-bus send --to agent-a --type pr:ready --payload '{...}'

# Agent C reviews — C is the "reviewer" in this moment
agent-bus send --to agent-b --type review:done --payload '{...}'
```

The same agent can play planner in one exchange and worker in another. Agent
Bus does not care.

## Examples

See the [`examples/`](../examples/) directory for reference Worker Runtime
implementations:

- [`examples/generic/run-task.sh`](../examples/generic/run-task.sh) — a
  minimal template that shows the lifecycle: receive, prepare, invoke, report
- [`examples/opencode/run-task.sh`](../examples/opencode/run-task.sh) — a
  concrete example using OpenCode as the local runtime

These scripts are reference implementations, not production tools. Adapt them
to your own runtime and workflow.

## What Agent Bus Does NOT Provide

The Worker Runtime is responsible for all of these. Agent Bus provides none
of them:

- Git operations (clone, checkout, pull, commit, push)
- AI model invocation or prompt construction
- Test frameworks or CI integration
- Workspace directory management
- PR / issue creation
- Memory or context management
- Workflow DAG or orchestration
- Agent selection or routing strategy
- Any tool-specific logic (OpenCode, Claude Code, Codex CLI, Hermes, etc.)

## Relationship to Agent Bus

```
┌──────────────────────────────────────────────────────┐
│                   A workflow runs here                │
│                                                      │
│  ┌──────────┐     ┌──────────┐     ┌──────────────┐  │
│  │ Sender   │────▶│Agent Bus │────▶│Worker Runtime│  │
│  │(planner) │     │(relay)   │     │(adapter)     │  │
│  └──────────┘     └──────────┘     └──────┬───────┘  │
│       ▲                                  │          │
│       └──────────────────────────────────┘          │
│                events flow back                     │
│                                                      │
│                          ┌──────────────────┐       │
│                          │ Local tool        │       │
│                          │ (OpenCode, Claude,│       │
│                          │  Codex, script)   │       │
│                          └──────────────────┘       │
└──────────────────────────────────────────────────────┘
```

Agent Bus only sees the events. It does not know which tool runs, where the
workspace lives, or how tasks are executed. That separation is what makes it a
relay, not a platform.
