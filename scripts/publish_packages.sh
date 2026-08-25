#!/usr/bin/env bash
set -e

echo "================================================================================"
echo " SYNAPSE-MESH DUAL PACKAGE PUBLISHER (npm & PyPI)"
echo "================================================================================"

# 1. Test Node.js Verifier package
echo -e "\n[1/3] Validating Node.js Standalone Verifier..."
cd packages/verify
npm pack --dry-run
cd ../..

# 2. Build Python wheel & tarball
echo -e "\n[2/3] Building Python Distribution Wheel..."
python3 -m pip install --upgrade build twine --quiet || true
python3 -m build

echo -e "\n[3/3] Ready for distribution!"
echo "To publish npm package:"
echo "  cd packages/verify && npm publish --access public"
echo ""
echo "To publish PyPI package:"
echo "  twine upload dist/*"
echo "================================================================================"
