#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "============================================================"
echo "E2E Test Runner — Compliance AI Platform"
echo "============================================================"
echo ""
echo "Prerequisites:"
echo "  - docker compose up -d (all services running)"
echo "  - Python packages: pytest pytest-asyncio httpx minio PyJWT"
echo ""

# Check docker compose is running
if ! docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps --services --filter "status=running" | grep -q "llm-gateway"; then
    echo "ERROR: Services not running. Start with: docker compose up -d"
    exit 1
fi

echo "[1/2] Seeding test data..."
python3 "$PROJECT_ROOT/testdata/setup.py"
echo ""

echo "[2/2] Running E2E tests..."
python -m pytest "$PROJECT_ROOT/tests/e2e/" -v --tb=short -m e2e
echo ""

echo "============================================================"
echo "Done."
echo "============================================================"
