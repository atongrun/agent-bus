#!/usr/bin/env bash
# Agent Bus — Minimal Self-Test Script
# Starts a local server and runs through all acceptance criteria.
#
# Usage:
#   bash scripts/test.sh

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
TEST_TOKEN="test-token-$(date +%s)"
ARCHITECT_TOKEN="architect-$TEST_TOKEN"
CODER_TOKEN="coder-$TEST_TOKEN"
TEST_PORT=18899
TEST_DB="/tmp/agent-bus-test-$$.db"
AGENT_BUS_URL="http://127.0.0.1:$TEST_PORT"
SERVER_PID=""

cleanup() {
    if [ -n "$SERVER_PID" ]; then
        kill $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
    fi
    rm -f "$TEST_DB" "$TEST_DB-wal" "$TEST_DB-shm"
}
trap cleanup EXIT

pass() {
    PASS=$((PASS + 1))
    echo -e "  ${GREEN}✓ PASS${NC}: $1"
}

fail() {
    FAIL=$((FAIL + 1))
    echo -e "  ${RED}✗ FAIL${NC}: $1"
    echo "    $2"
}

# --- Start server ---
if ! command -v uv > /dev/null 2>&1; then
    echo -e "${RED}uv is required to run this integration test.${NC}"
    echo "Install uv or run inside an environment that provides project dependencies."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo -e "${RED}Python 3.11+ is required. Found Python $PY_VERSION.${NC}"
    exit 1
fi

echo -e "${YELLOW}Running unit tests...${NC}"
uv run python -m unittest discover -s tests

echo -e "${YELLOW}Starting test server on $AGENT_BUS_URL...${NC}"
AGENT_BUS_AGENT_TOKENS="architect=$ARCHITECT_TOKEN,coder=$CODER_TOKEN" AGENT_BUS_DB_PATH="$TEST_DB" \
    uv run uvicorn server.main:app --host 127.0.0.1 --port $TEST_PORT &
SERVER_PID=$!
sleep 2

# Check server is alive
if curl -s "$AGENT_BUS_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}Server started.${NC}\n"
else
    echo -e "${RED}Server failed to start.${NC}"
    exit 1
fi

# ============================================================
echo "=== Test 1: Health Check ==="
RESP=$(curl -s "$AGENT_BUS_URL/health")
if echo "$RESP" | grep -q '"ok"'; then
    pass "Health check returns ok"
else
    fail "Health check failed" "$RESP"
fi

# ============================================================
echo ""
echo "=== Test 2: Create Event (valid auth) ==="
RESP=$(curl -s -X POST "$AGENT_BUS_URL/events" \
    -H "Authorization: Bearer $ARCHITECT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"architect","to_agent":"coder","type":"task:new","payload":{"url":"http://example.com"}}')
EVENT_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")

if [ -n "$EVENT_ID" ] && [ "$EVENT_ID" -gt 0 ] 2>/dev/null; then
    pass "Event created with id=$EVENT_ID, status=pending"
else
    fail "Failed to create event" "$RESP"
fi

# ============================================================
echo ""
echo "=== Test 3: Auth Rejection ==="
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_BUS_URL/events" \
    -H "Authorization: Bearer wrong-token" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"architect","to_agent":"coder","type":"task:new","payload":{}}')
if [ "$RESP" = "401" ]; then
    pass "Wrong token returns 401"
else
    fail "Wrong token should return 401" "Got: $RESP"
fi

# ============================================================
echo ""
echo "=== Test 4: Missing Auth ==="
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_BUS_URL/events" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"architect","to_agent":"coder","type":"task:new","payload":{}}')
if [ "$RESP" = "401" ]; then
    pass "Missing token returns 401"
else
    fail "Missing token should return 401" "Got: $RESP"
fi

# ============================================================
echo ""
echo "=== Test 5: ACK Event ==="
RESP=$(curl -s -X POST "$AGENT_BUS_URL/events/$EVENT_ID/ack" \
    -H "Authorization: Bearer $CODER_TOKEN")
ACK_STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "")

if [ "$ACK_STATUS" = "acked" ]; then
    pass "ACK marks event as acked"
else
    fail "ACK failed" "$RESP"
fi

# ============================================================
echo ""
echo "=== Test 6: ACK Idempotent (re-ACK same event) ==="
RESP=$(curl -s -X POST "$AGENT_BUS_URL/events/$EVENT_ID/ack" \
    -H "Authorization: Bearer $CODER_TOKEN")
REACK_STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "")

if [ "$REACK_STATUS" = "acked" ]; then
    pass "Re-ACK returns success (idempotent)"
else
    fail "Re-ACK should be idempotent" "$RESP"
fi

# ============================================================
echo ""
echo "=== Test 7: ACK Non-existent Event ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_BUS_URL/events/99999/ack" \
    -H "Authorization: Bearer $CODER_TOKEN")
if [ "$HTTP_CODE" = "404" ]; then
    pass "ACK non-existent event returns 404"
else
    fail "ACK non-existent should return 404" "Got: $HTTP_CODE"
fi

# ============================================================
echo ""
echo "=== Test 8: Offline → Online Delivery ==="
# Create event while no listener is active
RESP=$(curl -s -X POST "$AGENT_BUS_URL/events" \
    -H "Authorization: Bearer $ARCHITECT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"architect","to_agent":"coder","type":"task:new","payload":{"offline_test":true}}')
OFFLINE_EVENT_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")

# Now listen — should get the pending event
# Use -N for no-buffer, write to temp file to avoid shell buffering issues
SSE_TMP=$(mktemp)
timeout 3 curl -sN "$AGENT_BUS_URL/events/stream?agent=coder" \
    -H "Authorization: Bearer $CODER_TOKEN" > "$SSE_TMP" 2>&1 || true
SSE_OUTPUT=$(cat "$SSE_TMP")
rm -f "$SSE_TMP"

if echo "$SSE_OUTPUT" | grep -q "offline_test"; then
    pass "Offline event delivered on connect"
else
    fail "Offline event NOT delivered" "SSE output empty or missing data"
fi

# ACK that event
curl -s -X POST "$AGENT_BUS_URL/events/$OFFLINE_EVENT_ID/ack" \
    -H "Authorization: Bearer $CODER_TOKEN" > /dev/null

# ============================================================
echo ""
echo "=== Test 9: ACKed Events Not Replayed ==="
# Start another listen — should receive NO events (all ACKed)
SSE_TMP2=$(mktemp)
timeout 2 curl -sN "$AGENT_BUS_URL/events/stream?agent=coder" \
    -H "Authorization: Bearer $CODER_TOKEN" > "$SSE_TMP2" 2>&1 || true
SSE_OUTPUT2=$(cat "$SSE_TMP2")
rm -f "$SSE_TMP2"

# Should have no "data:" lines with actual events
DATA_COUNT=$(echo "$SSE_OUTPUT2" | grep -c "^data:" || true)
if [ "$DATA_COUNT" = "0" ] || [ -z "$DATA_COUNT" ]; then
    pass "ACKed events not replayed (no data lines in stream)"
else
    fail "ACKed events were replayed" "Got $DATA_COUNT data lines: $SSE_OUTPUT2"
fi

# ============================================================
echo ""
echo "=== Test 10: Multi-Agent Isolation ==="
# Event for coder should not be visible to architect
curl -s -X POST "$AGENT_BUS_URL/events" \
    -H "Authorization: Bearer $ARCHITECT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"architect","to_agent":"coder","type":"task:new","payload":{"secret":"for-coder"}}' > /dev/null

# Architect listener should NOT see events addressed to coder
ARCH_TMP=$(mktemp)
timeout 2 curl -sN "$AGENT_BUS_URL/events/stream?agent=architect" \
    -H "Authorization: Bearer $ARCHITECT_TOKEN" > "$ARCH_TMP" 2>&1 || true
ARCH_SSE=$(cat "$ARCH_TMP")
rm -f "$ARCH_TMP"

if echo "$ARCH_SSE" | grep -q "for-coder"; then
    fail "Architect received coder's event (isolation broken)" "$ARCH_SSE"
else
    pass "Agent isolation works (architect doesn't see coder events)"
fi

# ============================================================
echo ""
echo "=== Test 11: Validation — Empty Fields ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_BUS_URL/events" \
    -H "Authorization: Bearer $ARCHITECT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"","to_agent":"coder","type":"task:new","payload":{}}')
if [ "$HTTP_CODE" = "422" ]; then
    pass "Empty from_agent returns 422"
else
    fail "Empty from_agent should return 422" "Got: $HTTP_CODE"
fi

# ============================================================
echo ""
echo "=== Test 12: CLI send command ==="
CLI_OUTPUT=$(AGENT_BUS_URL="$AGENT_BUS_URL" AGENT_BUS_TOKEN="$ARCHITECT_TOKEN" AGENT_BUS_AGENT=architect \
    uv run agent-bus send --from architect --to coder --type task:new --payload '{"cli_test":true}' 2>&1 || true)
if echo "$CLI_OUTPUT" | grep -q "Event sent"; then
    pass "CLI send command works"
else
    fail "CLI send command failed" "$CLI_OUTPUT"
fi

# ============================================================
echo ""
echo "=== Test 13: Agent token cannot spoof from_agent ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_BUS_URL/events" \
    -H "Authorization: Bearer $CODER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"architect","to_agent":"coder","type":"task:new","payload":{}}')
if [ "$HTTP_CODE" = "403" ]; then
    pass "Coder token cannot send as architect"
else
    fail "Spoofed sender should return 403" "Got: $HTTP_CODE"
fi

# ============================================================
echo ""
echo "=== Test 14: Agent token cannot stream another agent ==="
FORBID_TMP=$(mktemp)
HTTP_CODE=$(timeout 2 curl -sN -o "$FORBID_TMP" -w "%{http_code}" "$AGENT_BUS_URL/events/stream?agent=architect" \
    -H "Authorization: Bearer $CODER_TOKEN" 2>/dev/null || true)
rm -f "$FORBID_TMP"
if [ "$HTTP_CODE" = "403" ]; then
    pass "Coder token cannot stream architect events"
else
    fail "Forbidden stream should return 403" "Got: $HTTP_CODE"
fi

# ============================================================
echo ""
echo "=== Test 15: Agent token cannot ACK another agent's event ==="
RESP=$(curl -s -X POST "$AGENT_BUS_URL/events" \
    -H "Authorization: Bearer $CODER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent":"coder","to_agent":"architect","type":"pr:ready","payload":{"task_id":"forbidden-ack"}}')
ARCH_EVENT_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$AGENT_BUS_URL/events/$ARCH_EVENT_ID/ack" \
    -H "Authorization: Bearer $CODER_TOKEN")
if [ "$HTTP_CODE" = "403" ]; then
    pass "Coder token cannot ACK architect event"
else
    fail "Forbidden ACK should return 403" "Got: $HTTP_CODE"
fi

# ============================================================
echo ""
echo "=== Test 16: Pending endpoint lists un-ACKed events ==="
RESP=$(curl -s "$AGENT_BUS_URL/events/pending?agent=architect" \
    -H "Authorization: Bearer $ARCHITECT_TOKEN")
if echo "$RESP" | grep -q "forbidden-ack"; then
    pass "Pending endpoint returns architect's un-ACKed event"
else
    fail "Pending endpoint did not return expected event" "$RESP"
fi

# ============================================================
# Summary
echo ""
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
echo -e "${YELLOW}========================================${NC}"

if [ "$FAIL" -gt 0 ]; then
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
