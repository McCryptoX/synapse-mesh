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

# Run within container or host python environment
if [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python"
fi

export PYTHONPATH="$PROJECT_DIR"

# 1. Run Upstream Mining Engine
echo "-> Executing Upstream Mining Engine..." >> "$LOG_FILE" 2>&1
$PYTHON_BIN -c "
import asyncio, logging
from app.core.upstream_miner import UpstreamMiningEngine
logging.basicConfig(level='INFO')
asyncio.run(UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=True))
" >> "$LOG_FILE" 2>&1 || true

# 2. Run GitHub Release Harvester & Batch Verification
echo "-> Executing GitHub Release Harvester & Batch Ingestion..." >> "$LOG_FILE" 2>&1
$PYTHON_BIN scripts/github_harvester.py >> "$LOG_FILE" 2>&1 || true

echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Harvester Run Complete ===" >> "$LOG_FILE" 2>&1
