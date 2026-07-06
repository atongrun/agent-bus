#!/usr/bin/env bash
# OpenCode Worker Runtime — reference example
#
# This is a concrete Worker Runtime that uses OpenCode as the local AI tool.
# It is NOT part of Agent Bus. Agent Bus does not know OpenCode exists.
#
# Usage:
#   agent-bus listen --agent coder --on task:new "bash run-task.sh {payload.task_id} '{payload.title}' '{payload.prompt}' {payload.repo} {payload.branch}"

set -euo pipefail

TASK_ID="${1:-unknown}"
TITLE="${2:-no title}"
PROMPT="${3:-}"
REPO="${4:-}"
BRANCH="${5:-main}"

AGENT_BUS_URL="${AGENT_BUS_URL:-http://localhost:8800}"
WORK_DIR="${WORK_DIR:-/tmp/agent-bus-tasks/${TASK_ID}}"

echo "╔══════════════════════════════════════╗"
echo "║  Worker received task: ${TASK_ID}"
echo "║  Title: ${TITLE}"
echo "╚══════════════════════════════════════╝"

# --- Prepare workspace ---
echo ""
echo "▶ Preparing workspace..."
rm -rf "${WORK_DIR}"
if [ -n "${REPO}" ]; then
    git clone --depth 1 --branch "${BRANCH}" "${REPO}" "${WORK_DIR}"
    cd "${WORK_DIR}"
else
    mkdir -p "${WORK_DIR}"
    cd "${WORK_DIR}"
fi

# --- Run OpenCode ---
echo ""
echo "▶ Running OpenCode..."
echo "   Prompt: ${PROMPT}"

# This is where the actual AI work happens. Agent Bus never sees this.
# You can replace 'opencode run' with 'claude --print', 'codex exec', etc.
opencode run "${PROMPT}"

# --- Report result ---
echo ""
echo "▶ Task ${TASK_ID} completed. The agent-bus listener will ACK this event."
# Exit 0 = success = agent-bus will ACK the event.
# Exit non-zero = agent-bus leaves the event un-ACKed for retry.
