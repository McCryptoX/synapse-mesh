#!/bin/sh
set -e

# The image declares the fixed non-root user; bind-mount ownership is prepared
# by deploy.sh before the container starts.
exec "$@"
