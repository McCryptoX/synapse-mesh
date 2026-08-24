#!/bin/bash
set -e

echo "=== Synapse-Mesh (Exocortex) Deployment ==="

# 1. Check Docker
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
fi

# 2. Create data directory
mkdir -p data

# 3. Build and Start Services
echo "Starting Docker Compose services..."
docker compose up -d --build

# 4. Seed initial recipes inside container
echo "Seeding initial verified recipes in container..."
docker compose exec -T api python scripts/seed_recipes.py || true

echo "=== Deployment Successful! ==="
echo "Synapse-Mesh is active at https://synapsemesh.dev"
echo "Status check: curl -I https://synapsemesh.dev/health"
