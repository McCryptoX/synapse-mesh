#!/bin/sh
set -e

# Ensure data directory exists and is fully writable by any user
mkdir -p /app/data
chmod 777 /app/data || true
if [ -f /app/data/synapse_mesh.sqlite3 ]; then
    chmod 666 /app/data/synapse_mesh.sqlite3* || true
fi

# Execute the main container command as synapse user
exec gosu synapse "$@"
