#!/bin/bash
set -e

echo "=== Synapse-Mesh (Exocortex) Deployment ==="

# 1. Create data directory with permissive access for sqlite non-root container
mkdir -p data
chmod -R 777 data

# 2. Build and Start Services
echo "Starting Docker Compose services..."
docker compose up -d --build

# 3. Fix permissions post-start
chmod -R 777 data

# 4. Seed initial recipes inside container if needed
echo "Seeding initial verified recipes in container..."
docker compose exec -T api python scripts/seed_recipes.py || true

echo "=== Deployment Successful! ==="
echo "Synapse-Mesh is active at https://synapsemesh.dev"
echo "Status check: curl -I https://synapsemesh.dev/health"
