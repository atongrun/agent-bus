#!/usr/bin/env bash
# Run the Docker server acceptance loop against isolated test resources.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ID="${AGENT_BUS_DOCKER_TEST_ID:-$$}"
case "$TEST_ID" in
    *[!A-Za-z0-9_.-]* | "")
        echo "AGENT_BUS_DOCKER_TEST_ID must contain only A-Za-z0-9_.-" >&2
        exit 64
        ;;
esac
TEST_PORT="${AGENT_BUS_DOCKER_TEST_PORT:-18898}"
TEST_VOLUME="agent-bus-test-${TEST_ID}"
TEST_IMAGE="agent-bus:test-${TEST_ID}"
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/agent-bus-docker-test.XXXXXX")"
ENV_FILE="$TEST_TMP/docker.env"
SENDER_TOKEN="sender-test-${TEST_ID}"
RECEIVER_TOKEN="receiver-test-${TEST_ID}"
BASE_URL="http://127.0.0.1:${TEST_PORT}"

compose() {
    docker compose \
        --project-name "agent-bus-test-${TEST_ID}" \
        --project-directory "$ROOT_DIR" \
        --file "$ROOT_DIR/compose.yaml" \
        --env-file "$ENV_FILE" \
        "$@"
}

cleanup() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then
        compose logs --no-color agent-bus 2>/dev/null || true
    fi
    compose down --remove-orphans 2>/dev/null || true
    docker volume rm "$TEST_VOLUME" >/dev/null 2>&1 || true
    docker image rm "$TEST_IMAGE" >/dev/null 2>&1 || true
    rm -f "$ENV_FILE"
    rmdir "$TEST_TMP" 2>/dev/null || true
    exit "$status"
}
trap cleanup EXIT

cat > "$ENV_FILE" <<EOF
AGENT_BUS_AGENT_TOKENS=sender=$SENDER_TOKEN,receiver=$RECEIVER_TOKEN
AGENT_BUS_BIND_ADDRESS=127.0.0.1
AGENT_BUS_PUBLISHED_PORT=$TEST_PORT
AGENT_BUS_DATA_VOLUME=$TEST_VOLUME
AGENT_BUS_IMAGE=$TEST_IMAGE
EOF
chmod 600 "$ENV_FILE"

wait_for_health() {
    local attempt
    for attempt in $(seq 1 30); do
        if curl --fail --silent "$BASE_URL/health" >/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "Docker health check did not pass at $BASE_URL" >&2
    return 1
}

echo "Validating Compose configuration..."
compose config --quiet

echo "Building and starting isolated Docker deployment..."
compose up -d --build
wait_for_health

echo "Sending a durable event..."
EVENT_ID="$(
    curl --fail --silent \
        -X POST "$BASE_URL/events" \
        -H "Authorization: Bearer $SENDER_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"from_agent":"sender","to_agent":"receiver","type":"task:new","payload":{"docker_test":true}}' |
        python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
)"

PENDING_BEFORE="$(
    curl --fail --silent "$BASE_URL/events/pending?agent=receiver" \
        -H "Authorization: Bearer $RECEIVER_TOKEN"
)"
PENDING_JSON="$PENDING_BEFORE" EXPECTED_ID="$EVENT_ID" python3 -c \
    'import json,os; assert any(item["id"] == int(os.environ["EXPECTED_ID"]) for item in json.loads(os.environ["PENDING_JSON"]))'

echo "Recreating the container while preserving the named volume..."
compose up -d --force-recreate --no-build
wait_for_health

PENDING_AFTER="$(
    curl --fail --silent "$BASE_URL/events/pending?agent=receiver" \
        -H "Authorization: Bearer $RECEIVER_TOKEN"
)"
PENDING_JSON="$PENDING_AFTER" EXPECTED_ID="$EVENT_ID" python3 -c \
    'import json,os; assert any(item["id"] == int(os.environ["EXPECTED_ID"]) for item in json.loads(os.environ["PENDING_JSON"]))'

echo "ACKing the persisted event and checking the queue is empty..."
curl --fail --silent \
    -X POST "$BASE_URL/events/$EVENT_ID/ack" \
    -H "Authorization: Bearer $RECEIVER_TOKEN" >/dev/null

PENDING_FINAL="$(
    curl --fail --silent "$BASE_URL/events/pending?agent=receiver" \
        -H "Authorization: Bearer $RECEIVER_TOKEN"
)"
PENDING_JSON="$PENDING_FINAL" python3 -c \
    'import json,os; assert json.loads(os.environ["PENDING_JSON"]) == []'

echo "Docker acceptance passed: health, send, pending, recreate persistence, ACK, pending empty."
