#!/usr/bin/env bash
# Agent Bus Server Installation Script
# Run this on your VPS to set up the Agent Bus server.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/xxx/agent-bus/main/scripts/install.sh | bash
#   # Or locally:
#   bash scripts/install.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Agent Bus Server Installer ===${NC}"

# --- Detect OS ---
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo -e "${RED}Cannot detect OS. Only Ubuntu/Debian supported.${NC}"
    exit 1
fi

echo "Detected OS: $OS"

# --- Install system dependencies ---
echo -e "\n${YELLOW}[1/5] Installing system dependencies...${NC}"
if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv curl
elif command -v yum &> /dev/null; then
    sudo yum install -y python3 python3-pip curl
elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 python3-pip curl
else
    echo -e "${RED}Unsupported package manager. Install Python 3.11+ manually.${NC}"
    exit 1
fi

# --- Create agent-bus user ---
echo -e "\n${YELLOW}[2/5] Creating agent-bus system user...${NC}"
if ! id -u agent-bus &>/dev/null; then
    sudo useradd -r -m -d /opt/agent-bus -s /bin/bash agent-bus
    echo "User agent-bus created."
else
    echo "User agent-bus already exists."
fi

# --- Install application ---
echo -e "\n${YELLOW}[3/5] Installing agent-bus...${NC}"
INSTALL_DIR="/opt/agent-bus/app"

if [ ! -d "$INSTALL_DIR" ]; then
    # If run from the repo directory, copy it
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_DIR="$(dirname "$SCRIPT_DIR")"

    if [ -f "$REPO_DIR/pyproject.toml" ]; then
        echo "Copying from $REPO_DIR to $INSTALL_DIR..."
        sudo mkdir -p "$INSTALL_DIR"
        sudo cp -r "$REPO_DIR"/* "$INSTALL_DIR/"
    else
        echo -e "${RED}Repository not found. Clone agent-bus first or run this script from the repo.${NC}"
        exit 1
    fi
fi

sudo chown -R agent-bus:agent-bus "$INSTALL_DIR"

# Install with pip into a venv
echo "Installing Python dependencies..."
cd "$INSTALL_DIR"
sudo -u agent-bus python3 -m venv .venv
sudo -u agent-bus .venv/bin/pip install -e . --quiet

# --- Configure ---
echo -e "\n${YELLOW}[4/5] Configuring agent-bus...${NC}"
CONFIG_DIR="/etc/agent-bus"
sudo mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/.env" ]; then
    # Generate per-agent tokens
    ARCHITECT_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    CODER_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sudo tee "$CONFIG_DIR/.env" > /dev/null <<EOF
AGENT_BUS_AGENT_TOKENS=architect=$ARCHITECT_TOKEN,coder=$CODER_TOKEN
AGENT_BUS_HOST=0.0.0.0
AGENT_BUS_PORT=8800
AGENT_BUS_DB_PATH=/opt/agent-bus/data/agent-bus.db
EOF
    sudo chmod 600 "$CONFIG_DIR/.env"
    echo -e "${GREEN}Config created at $CONFIG_DIR/.env${NC}"
    echo -e "${YELLOW}Architect token: $ARCHITECT_TOKEN${NC}"
    echo -e "${YELLOW}Coder token:     $CODER_TOKEN${NC}"
    echo "Save these tokens! Each client should use only its own token."
else
    echo "Config already exists at $CONFIG_DIR/.env"
fi

# Create data directory
sudo mkdir -p /opt/agent-bus/data
sudo chown -R agent-bus:agent-bus /opt/agent-bus/data

# --- Install systemd service ---
echo -e "\n${YELLOW}[5/5] Installing systemd service...${NC}"
sudo cp "$INSTALL_DIR/scripts/agent-bus.service" /etc/systemd/system/agent-bus.service
sudo systemctl daemon-reload
sudo systemctl enable agent-bus
sudo systemctl start agent-bus

sleep 2
if systemctl is-active --quiet agent-bus; then
    echo -e "${GREEN}✓ Agent Bus is running!${NC}"
    echo ""
    echo "  Status: sudo systemctl status agent-bus"
    echo "  Logs:   sudo journalctl -u agent-bus -f"
    echo "  Health: curl http://localhost:8800/health"
else
    echo -e "${RED}✗ Agent Bus failed to start. Check logs: sudo journalctl -u agent-bus -n 50${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=== Installation Complete ===${NC}"
echo ""
echo "Client configuration (on Mac/Windows):"
echo "  agent-bus context add <name> --server http://<private-host>:8800 \\"
echo "    --agent <agent-name> --token-env AGENT_BUS_CLIENT_TOKEN \\"
echo "    --env-file <absolute-owner-only-credentials-file> --select"
echo "  (credential file entry: AGENT_BUS_CLIENT_TOKEN=<agent-specific-token>)"
echo "  agent-bus doctor"
echo ""
echo "Test from client:"
echo "  agent-bus send --to <receiver> --type task:new --payload '{\"test\":true}'"
echo "  agent-bus listen"
echo ""
echo "CI/compatibility: AGENT_BUS_URL, AGENT_BUS_TOKEN, and AGENT_BUS_AGENT remain supported."
