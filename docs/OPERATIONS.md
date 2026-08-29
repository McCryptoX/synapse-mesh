# Synapse-Mesh Operations & Revival Guide

This document provides complete instructions for deploying, maintaining, backing up, troubleshooting, and reviving Synapse-Mesh on a new server.

---

## 1. System Requirements & Prerequisites

### 1.1 Hardware Specifications
- **CPU:** 1 vCPU (2 vCPUs recommended for concurrent verification).
- **RAM:** Minimum 1 GB (2 GB recommended).
- **Disk Storage:** 10 GB SSD space.
- **Architecture:** `x86_64` or `aarch64` (Linux).

### 1.2 Software Requirements
- **Operating System:** Ubuntu 22.04 LTS, 24.04 LTS, 26.04 LTS, or Debian 12+.
- **Docker Engine:** Docker 24.0+ with Compose V2 (`docker compose`).
- **Python:** Python 3.11+ (used for host-side backup script and verification runner).
- **Systemd:** Required for scheduled background verification timers.

### 1.3 Networking & DNS
- Ports open to internet: `80/tcp` (HTTP) and `443/tcp` (HTTPS).
- DNS A/AAAA records configured for your domain:
  - Apex domain: `@` -> Server IP
  - Subdomains: `mcp`, `api`, `docs` -> Server IP (or wildcard `*`)

---

## 2. Directory Layout & Persistence Model

When deployed under `/opt/synapse-mesh`:

```text
/opt/synapse-mesh/
├── Caddyfile                   # Edge proxy configuration
├── Dockerfile                  # Application image specification
├── docker-compose.yml          # Container service definition
├── deploy.sh                   # Atomic deployment & health validation script
├── .env                        # Production secrets & environment (DO NOT COMMIT)
├── app/                        # Read-only application source
├── bundles/
│   ├── golden/                 # Read-only curated compatibility bundles
│   └── drafts/                 # WRITABLE: Candidate bundles from miner/submissions
├── data/
│   └── synapse_mesh.sqlite3    # WRITABLE: Production SQLite database (WAL mode)
├── deploy/
│   └── systemd/                # Host systemd service and timer units
├── evidence/
│   ├── runs/                   # WRITABLE (Host only): Verified run output artifacts
│   └── lifecycle/              # Read-only: Bundle lifecycle & expiration records
└── scripts/                    # Maintenance & verification utilities
```

### Critical Preservation Rules:
- **`data/`**: Must NEVER be deleted or overwritten by a deployment. Holds SQLite database and draft state.
- **`bundles/drafts/`**: Must be preserved across deployments.
- **`evidence/runs/`**: Contains immutable run evidence. Preserved across deploys.
- **`/opt/synapse-backups/`**: Host-level directory for pre-deploy SQLite snapshots.

---

## 3. Initial Server Deployment (Fresh Setup)

### Step 1: Install System Dependencies
```bash
# Update package list and install requirements
sudo apt-get update
sudo apt-get install -y git curl python3 python3-venv docker.io docker-compose-v2

# Enable and start Docker service
sudo systemctl enable --now docker
```

### Step 2: Clone Repository
```bash
sudo install -d -m 0755 -o $(whoami) -g $(whoami) /opt/synapse-mesh
git clone https://github.com/McCryptoX/synapse-mesh.git /opt/synapse-mesh
cd /opt/synapse-mesh
```

### Step 3: Configure Production Environment
```bash
# Copy example configuration
cp .env.example .env

# Generate secure random tokens
ADMIN_SECRET=$(openssl rand -hex 24)
OPS_PASSWORD=$(openssl rand -hex 16)

# Edit .env with your domain and generated secrets
sed -i "s/ENVIRONMENT=development/ENVIRONMENT=production/" .env
sed -i "s/replace-with-a-strong-random-admin-secret-key/$ADMIN_SECRET/" .env
sed -i "s/replace-with-a-strong-random-ops-password/$OPS_PASSWORD/" .env
```

### Step 4: Run Initial Deployment
```bash
# Set SYNAPSE_ALLOW_EMPTY_DATABASE=1 only on the very first install to initialize SQLite
SYNAPSE_ALLOW_EMPTY_DATABASE=1 ./deploy.sh
```

`deploy.sh` automatically:
1. Validates Docker Compose configuration.
2. Initializes directory structures with secure permissions (`umask 027`, user `10001:10001`).
3. Builds and starts `synapse_api` and `synapse_caddy` containers.
4. Installs and enables host-side systemd verification timers (`synapse-verification.timer`).
5. Executes automated end-to-end smoke tests against the public endpoints.

---

## 4. Routine Deployment & Updates

To deploy an update from Git:

```bash
cd /opt/synapse-mesh
git pull origin main
./deploy.sh
```

`deploy.sh` performs an online, zero-downtime atomic backup of SQLite to `/opt/synapse-backups/` before recreating containers. If health checks fail, the old state remains safely restorable.

---

## 5. Health Checks & Operational Verification

Verify the system status using standard HTTP checks:

```bash
# 1. API Health & Database Status
curl -fsSL https://synapsemesh.dev/health

# 2. MCP Discovery Descriptor
curl -fsSL https://synapsemesh.dev/.well-known/mcp.json

# 3. MCP JSON-RPC Smoke Test
curl -fsSL -X POST https://synapsemesh.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"ping","method":"initialize","params":{"protocolVersion":"2024-11-05"}}'

# 4. Check Container Status
docker compose ps

# 5. Check Systemd Verification Timer
systemctl status synapse-verification.timer
```

---

## 6. Database Operations & Backups

### 6.1 Database Location & Properties
- Path: `/opt/synapse-mesh/data/synapse_mesh.sqlite3`
- Journal Mode: `WAL` (Write-Ahead Logging)
- Backups Location: `/opt/synapse-backups/`

### 6.2 Manual Online Backup
To create a safe SQLite backup without stopping the service:

```bash
python3 - << 'PY'
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup_path = f"/opt/synapse-backups/manual_backup_{timestamp}.sqlite3"

source = sqlite3.connect("file:/opt/synapse-mesh/data/synapse_mesh.sqlite3?mode=ro", uri=True)
dest = sqlite3.connect(backup_path)
source.backup(dest)
dest.close()
source.close()
print(f"Backup successfully created at {backup_path}")
PY
```

### 6.3 Integrity Verification
```bash
python3 -c "import sqlite3; conn = sqlite3.connect('/opt/synapse-mesh/data/synapse_mesh.sqlite3'); print('Quick check:', conn.execute('PRAGMA quick_check').fetchone()[0])"
```

### 6.4 Database Restore
If the database becomes corrupted or needs to be rolled back:

```bash
# 1. Stop API container
docker compose stop api

# 2. Copy the desired backup into place
cp /opt/synapse-backups/synapse_mesh.pre-deploy-<TIMESTAMP>.sqlite3 /opt/synapse-mesh/data/synapse_mesh.sqlite3
chmod 0640 /opt/synapse-mesh/data/synapse_mesh.sqlite3
chown 10001:10001 /opt/synapse-mesh/data/synapse_mesh.sqlite3

# 3. Restart services
docker compose up -d api
```

---

## 7. Troubleshooting & Recovery Procedures

### 7.1 API Service Unhealthy
```bash
# Inspect container logs
docker compose logs --tail=100 api

# Restart API container
docker compose restart api
```

### 7.2 Caddy / TLS Certificate Renewal Issues
```bash
# Check Caddy logs
docker compose logs --tail=100 caddy

# Validate Caddy configuration syntax
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# Reload Caddy without downtime
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

### 7.3 Verification Timer Failures
```bash
# Check systemd service status
systemctl status synapse-verification.service

# View execution logs
journalctl -u synapse-verification.service -n 50 --no-pager
```

---

## 8. Migration to a New Server (Complete Revival)

Follow these steps to revive the entire project on a completely new host:

1. **Provision New Host:** Set up Ubuntu 24.04 LTS (1-2 vCPU, 2 GB RAM).
2. **Point DNS:** Update A/AAAA DNS records to the new host IP.
3. **Install Docker & Git:**
   ```bash
   sudo apt-get update && sudo apt-get install -y git python3 docker.io docker-compose-v2
   sudo systemctl enable --now docker
   ```
4. **Clone Repository:**
   ```bash
   git clone https://github.com/McCryptoX/synapse-mesh.git /opt/synapse-mesh
   cd /opt/synapse-mesh
   ```
5. **Configure `.env`:** Copy `.env.example` to `.env` and set `ENVIRONMENT=production`, `DOMAIN`, `ADMIN_TOKEN`, and `OPS_PASSWORD`.
6. **Transfer State (Optional):**
   If you have a backup from the previous host:
   ```bash
   # Copy SQLite database backup
   mkdir -p /opt/synapse-mesh/data
   scp user@old-server:/opt/synapse-backups/latest.sqlite3 /opt/synapse-mesh/data/synapse_mesh.sqlite3

   # Copy persistent evidence runs (if any)
   scp -r user@old-server:/opt/synapse-mesh/evidence/runs /opt/synapse-mesh/evidence/
   ```
7. **Deploy Services:**
   ```bash
   # If starting fresh without old database:
   SYNAPSE_ALLOW_EMPTY_DATABASE=1 ./deploy.sh

   # If database was restored:
   ./deploy.sh
   ```
8. **Verify Public Endpoints:**
   ```bash
   curl -I https://<YOUR-DOMAIN>/health
   ```
