#!/usr/bin/env bash
# ==============================================================================
# Synapse-Mesh Agent MCP Configurator
# Safely registers Synapse-Mesh MCP server in Cursor, Claude Desktop, Claude Code.
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
echo "Verified Compatibility Layer for AI Coding Agents (MCP Spec 2026-07-28)"
echo "--------------------------------------------------------------------------------"

# 1. Health Verification
echo -n "Checking connection to Synapse-Mesh live node... "
HEALTH=$(curl -s https://synapsemesh.dev/health || echo "FAIL")
if [[ "$HEALTH" =~ "healthy" ]]; then
    echo -e "${GREEN}[OK]${NC}"
else
    echo -e "${YELLOW}[WARN: Offline or Degraded]${NC}"
fi

CONFIG_FOUND=0

inject_mcp() {
    local target_file="$1"
    local app_name="$2"
    mkdir -p "$(dirname "$target_file")"
    
    python3 -c "
import json, os, sys

path = '$target_file'
data = {}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'Warning: Preserving existing unparseable config at {path}', file=sys.stderr)
        sys.exit(0)

if 'mcpServers' not in data:
    data['mcpServers'] = {}

data['mcpServers']['synapse-mesh'] = {
    'url': 'https://mcp.synapsemesh.dev/mcp',
    'type': 'streamable-http'
}

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
"
    echo -e "${GREEN}[✓] Registered Synapse-Mesh MCP in ${app_name}:${NC} ${target_file}"
    CONFIG_FOUND=1
}

# 2. Claude Desktop (Only if application directory actually exists)
CLAUDE_MAC="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
CLAUDE_LINUX="$HOME/.config/Claude/claude_desktop_config.json"

if [ -d "$HOME/Library/Application Support/Claude" ]; then
    inject_mcp "$CLAUDE_MAC" "Claude Desktop (macOS)"
elif [ -d "$HOME/.config/Claude" ]; then
    inject_mcp "$CLAUDE_LINUX" "Claude Desktop (Linux)"
fi

# 3. Cursor
if [ -d "$HOME/.cursor" ]; then
    inject_mcp "$HOME/.cursor/mcp.json" "Cursor Editor"
fi

# 4. Antigravity CLI
if [ -d "$HOME/.gemini/antigravity-cli" ]; then
    inject_mcp "$HOME/.gemini/antigravity-cli/mcp_config.json" "Google Antigravity"
fi

# 5. Fallback local config
if [ "$CONFIG_FOUND" -eq 0 ]; then
    LOCAL_CONFIG="$HOME/.synapse-mesh/mcp.json"
    inject_mcp "$LOCAL_CONFIG" "Generic MCP Client"
fi

echo "--------------------------------------------------------------------------------"
echo -e "${GREEN}Configuration Complete!${NC}"
echo "AI coding agents can now query verified compatibility bundles via 'find_solution'."
echo "Endpoint: https://mcp.synapsemesh.dev/mcp"
