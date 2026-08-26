#!/usr/bin/env bash
set -e

# ==============================================================================
# Synapse-Mesh Autonomous Harvester & Ingestion Runner
# ==============================================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

LOCK_FILE="/tmp/synapse_harvester.lock"
LOG_FILE="/opt/synapse-mesh/data/harvester.log"

# Check if lock exists and is held by a live process
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Harvester already running with PID $PID. Skipping."
        exit 0
    fi
fi

echo "$$" > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting Synapse-Mesh Autonomous Harvester ===" >> "$LOG_FILE" 2>&1

# Run harvester inside the docker container where all dependencies (pydantic, httpx, etc.) are installed
if docker ps --format '{{.Names}}' | grep -q "synapse_api"; then
    EXEC_CMD="docker exec synapse_api python3"
elif [ -f ".venv/bin/python" ]; then
    EXEC_CMD=".venv/bin/python"
else
    EXEC_CMD="python3"
fi

# 1. Run Upstream Mining Engine
echo "-> Executing Upstream Mining Engine..." >> "$LOG_FILE" 2>&1
$EXEC_CMD -c "
import asyncio, logging
from app.core.upstream_miner import UpstreamMiningEngine
logging.basicConfig(level='INFO')
asyncio.run(UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=True))
" >> "$LOG_FILE" 2>&1 || true

# 2. Run GitHub Release Harvester & Batch Verification
echo "-> Executing GitHub Release Harvester & Batch Ingestion..." >> "$LOG_FILE" 2>&1
$EXEC_CMD scripts/github_harvester.py >> "$LOG_FILE" 2>&1 || true

echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Harvester Run Complete ===" >> "$LOG_FILE" 2>&1
