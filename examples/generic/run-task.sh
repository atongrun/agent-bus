#!/usr/bin/env bash
# Generic Worker Runtime — reference template
#
# This is a minimal example of what a Worker Runtime can look like.
# It shows the lifecycle: receive → decide → prepare → invoke → report.
# Adapt it for your own runtime and workflow.
#
# Usage:
#   WORKER_COMMAND=your-tool \
#     agent-bus listen --agent worker --on task:new \
#       "bash run-task.sh {payload.task_id} '{payload.title}' '{payload.prompt}' '{payload.repo}' '{payload.branch}'"

set -euo pipefail

# --- Configuration (set via environment or agent-bus template variables) ---
AGENT_BUS_URL="${AGENT_BUS_URL:-http://localhost:8800}"
AGENT_BUS_TOKEN="${AGENT_BUS_TOKEN:-}"
AGENT_BUS_AGENT="${AGENT_BUS_AGENT:-worker}"
TASK_ID="${1:-unknown}"
TITLE="${2:-no title}"
PROMPT="${3:-}"
REPO="${4:-}"
BRANCH="${5:-main}"
TO_AGENT="${6:-}"
WORKER_COMMAND="${WORKER_COMMAND:-}"

WORK_DIR="${WORK_DIR:-/tmp/agent-bus-tasks/${TASK_ID}}"

echo "[worker] Received task: ${TASK_ID} — ${TITLE}"

# --- Decide whether to handle this task ---
if [ -z "${PROMPT}" ]; then
    echo "[worker] No prompt provided — skipping"
    exit 0
fi

# --- Prepare workspace ---
echo "[worker] Preparing workspace: ${WORK_DIR}"
rm -rf "${WORK_DIR}"
if [ -n "${REPO}" ]; then
    git clone --depth 1 --branch "${BRANCH}" "${REPO}" "${WORK_DIR}" || {
        echo "[worker] git clone failed"
        exit 1
    }
else
    mkdir -p "${WORK_DIR}"
fi
cd "${WORK_DIR}"

# --- Invoke the local tool ---
# Set WORKER_COMMAND to an executable, or replace this block with your adapter.
# The task prompt is passed as data, not evaluated as shell.
if [ -z "${WORKER_COMMAND}" ]; then
    echo "[worker] WORKER_COMMAND is not set"
    exit 1
fi

echo "[worker] Invoking local tool: ${WORKER_COMMAND}"
"${WORKER_COMMAND}" "${PROMPT}" || {
    echo "[worker] Task failed"
    exit 1
}

echo "[worker] Task completed successfully"
# The agent-bus listener will ACK this event when this script exits 0.
