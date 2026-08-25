#!/usr/bin/env bash
# ==============================================================================
# Synapse-Mesh One-Liner Agent Installer
# Auto-detects Cursor, Claude Desktop, Claude Code, and Antigravity MCP configs.
# ==============================================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ___                                   __  __           _     "
echo " / __|_  _ _ _  __ _ _ __  ___ ___ ___ |  \/  |___ _____| |_   "
echo " \__ \ || | ' \/ _\` | '_ \(_-</ -_)___| |\/| / -_|_-< ' \ ' \  "
echo " |___/\_, |_||_\__,_| .__/__/\___|     |_|  |_\___/__/_||_||_| "
echo "      |__/          |_|                                        "
echo -e "${NC}"
echo "Agent-Native Living Solutions & Verification Infrastructure (MCP Spezifikation 2026-07-28)"
echo "--------------------------------------------------------------------------------"

# 1. Health Verification
echo -n "Checking connection to Synapse-Mesh live node... "
HEALTH=$(curl -s https://api.synapsemesh.dev/health || echo "FAIL")
if [[ "$HEALTH" =~ "healthy" ]]; then
    echo -e "${GREEN}[OK]${NC}"
else
    echo -e "${YELLOW}[WARN: Offline or Degraded]${NC}"
fi

CONFIG_FOUND=0

# Helper function to inject MCP entry safely with Python
inject_mcp() {
    local target_file="$1"
    local app_name="$2"
    mkdir -p "$(dirname "$target_file")"
    
    python3 -c "
import json, os

path = '$target_file'
data = {}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}

if 'mcpServers' not in data:
    data['mcpServers'] = {}

data['mcpServers']['synapse-mesh'] = {
    'url': 'https://mcp.synapsemesh.dev/mcp',
    'type': 'streamable-http'
}

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
"
    echo -e "${GREEN}[✓] Successfully registered Synapse-Mesh MCP in ${app_name}:${NC} ${target_file}"
    CONFIG_FOUND=1
}

# 2. Detect Claude Desktop (macOS / Linux)
CLAUDE_MAC="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
CLAUDE_LINUX="$HOME/.config/Claude/claude_desktop_config.json"

if [ -d "$HOME/Library/Application Support/Claude" ] || [ "$(uname)" == "Darwin" ]; then
    inject_mcp "$CLAUDE_MAC" "Claude Desktop (macOS)"
elif [ -d "$HOME/.config/Claude" ]; then
    inject_mcp "$CLAUDE_LINUX" "Claude Desktop (Linux)"
fi

# 3. Detect Cursor (.cursor or global)
CURSOR_DIR="$HOME/.cursor"
if [ -d "$CURSOR_DIR" ]; then
    inject_mcp "$HOME/.cursor/mcp.json" "Cursor Editor"
fi

# 4. Detect Antigravity CLI
ANTIGRAVITY_DIR="$HOME/.gemini/antigravity-cli"
if [ -d "$ANTIGRAVITY_DIR" ]; then
    inject_mcp "$ANTIGRAVITY_DIR/mcp_config.json" "Google Antigravity"
fi

# 5. Fallback local config
if [ "$CONFIG_FOUND" -eq 0 ]; then
    LOCAL_CONFIG="$HOME/.synapse-mesh/mcp.json"
    inject_mcp "$LOCAL_CONFIG" "Generic MCP Client"
fi

echo "--------------------------------------------------------------------------------"
echo -e "${GREEN}Installation Complete!${NC}"
echo "Synapse-Mesh is ready. Your AI coding agents can now query verified recipes via 'find_solution'."
echo "Endpoint: https://mcp.synapsemesh.dev/mcp"
