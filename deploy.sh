#!/bin/sh
set -eu

umask 027

exec 9>/run/lock/synapse-mesh-deploy.lock
if ! flock -n 9; then
    echo "Deployment failed: another deployment is already running." >&2
    exit 1
fi

echo "=== Synapse-Mesh (Exocortex) Deployment ==="

# 1. Validate configuration and create only the required writable bind mounts.
docker compose config -q
install -d -m 0750 data bundles/drafts
if [ -L evidence/runs ] || [ -L evidence/lifecycle ]; then
    echo "Deployment failed: evidence directories must not be symlinks." >&2
    exit 1
fi
install -d -m 0755 evidence/runs evidence/lifecycle
install -d -m 0700 /opt/synapse-backups

if [ ! -f data/synapse_mesh.sqlite3 ] && [ "${SYNAPSE_ALLOW_EMPTY_DATABASE:-0}" != "1" ]; then
    echo "Deployment failed: production SQLite is missing. Set SYNAPSE_ALLOW_EMPTY_DATABASE=1 only for an intentional first install." >&2
    exit 1
fi

# 2. Back up and integrity-check production SQLite before startup migrations.
if [ -f data/synapse_mesh.sqlite3 ]; then
    backup_name="synapse_mesh.pre-deploy-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
    backup_path="/opt/synapse-backups/$backup_name"
    echo "Creating consistent SQLite backup outside the application mount: $backup_path"
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Refusing deployment: host python3 is required for the SQLite online backup." >&2
        exit 1
    fi
    SYNAPSE_BACKUP_PATH="$backup_path" python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

source_path = Path("data/synapse_mesh.sqlite3")
backup_path = Path(os.environ["SYNAPSE_BACKUP_PATH"])
if backup_path.exists():
    raise RuntimeError("refusing to overwrite an existing backup")

source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
try:
    if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise RuntimeError("source SQLite quick_check failed")
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("backup SQLite quick_check failed")
    finally:
        destination.close()
finally:
    source.close()
PY
    chmod 0600 "$backup_path"
fi

# The fixed container user owns only the two writable application mounts.
chown -R 10001:10001 data bundles/drafts

# 3. Build and start services only after the backup succeeds.
echo "Starting Docker Compose services..."
docker compose up -d --build --force-recreate

attempt=0
while [ "$attempt" -lt 30 ]; do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' synapse_api 2>/dev/null || true)"
    if [ "$health" = "healthy" ]; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 2
done

if [ "${health:-}" != "healthy" ]; then
    echo "Deployment failed: API container did not become healthy." >&2
    docker compose ps >&2
    exit 1
fi

docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"

# 4. Refresh only exact allowlisted trusted fixtures from a host-level timer.
# The API receives evidence through a read-only mount and never receives the
# Docker socket or permission to launch verification jobs itself.
if ! command -v systemctl >/dev/null 2>&1; then
    echo "Deployment failed: systemd is required for autonomous evidence refresh." >&2
    exit 1
fi
install -m 0644 deploy/systemd/synapse-verification.service /etc/systemd/system/synapse-verification.service
install -m 0644 deploy/systemd/synapse-verification.timer /etc/systemd/system/synapse-verification.timer
systemctl daemon-reload
systemctl enable --now synapse-verification.timer >/dev/null

# 5. Fail closed unless public TLS, discovery, MCP, and the migrated database
# all agree after the container restart. This writes no production test data.
python3 - <<'PY'
import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

base = "https://synapsemesh.dev"


def read_json(path: str, *, data: bytes | None = None) -> dict:
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP {response.status} for {path}")
        return json.load(response)


health = read_json("/health")
if health.get("status") != "healthy":
    raise RuntimeError("public health response is not healthy")

manifest = read_json("/.well-known/mcp.json")
if manifest.get("transport", {}).get("endpoint") != "https://mcp.synapsemesh.dev/mcp":
    raise RuntimeError("canonical MCP discovery endpoint drifted")

for path in ("/legal", "/privacy", "/openapi.json"):
    read_json(path) if path.endswith(".json") else urllib.request.urlopen(base + path, timeout=10).close()

for path in ("/impressum", "/datenschutz"):
    try:
        urllib.request.urlopen(base + path, timeout=10)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    else:
        raise RuntimeError(f"legacy legal alias unexpectedly exists: {path}")

initialize = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": "deploy-smoke",
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    }
).encode()
mcp = read_json("/mcp", data=initialize)
if mcp.get("result", {}).get("serverInfo", {}).get("name") != "synapse-mesh":
    raise RuntimeError("MCP initialize smoke failed")

database = Path("data/synapse_mesh.sqlite3").resolve()
connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
try:
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise RuntimeError("post-deploy SQLite quick_check failed")
    remaining_queries = connection.execute(
        "SELECT COUNT(*) FROM access_logs "
        "WHERE query_snippet IS NOT NULL AND trim(query_snippet) != ''"
    ).fetchone()[0]
    if remaining_queries:
        raise RuntimeError("post-deploy privacy migration left query snippets")
finally:
    connection.close()
PY

echo "=== Deployment Successful! ==="
echo "Synapse-Mesh is active at https://synapsemesh.dev"
echo "Status check: curl -I https://synapsemesh.dev/health"
