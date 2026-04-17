#!/bin/bash
# End-to-end test runner for Ship container
# Usage: ./run_e2e_tests.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
IMAGE_NAME="soulter/shipyard-ship:e2e-test"
CONTAINER_NAME="ship-e2e-test"
HOST_PORT=18123

echo "=== Ship E2E Test Runner ==="
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo "==> Cleaning up..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
}

# Register cleanup handler
trap cleanup EXIT

# Step 1: Build the image
echo "==> Building Docker image..."
docker build -t "$IMAGE_NAME" "$PROJECT_ROOT"

# Step 2: Stop any existing container
echo "==> Stopping existing container (if any)..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# Step 3: Start the container
echo "==> Starting Ship container..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -p "$HOST_PORT:8123" \
    -v /tmp/ship-e2e-workspace:/workspace \
    "$IMAGE_NAME"

# Step 4: Wait for the container to be ready
echo "==> Waiting for Ship to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
BASE_URL="http://127.0.0.1:$HOST_PORT"

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s "$BASE_URL/health" | grep -q "healthy"; then
        echo "    Ship is ready!"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "    Waiting... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 1
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "ERROR: Ship failed to start within timeout"
    echo "Container logs:"
    docker logs "$CONTAINER_NAME"
    exit 1
fi

# Step 5: Run the tests
echo ""
echo "==> Running E2E tests..."
export SHIP_BASE_URL="$BASE_URL"
cd "$PROJECT_ROOT"

# Run tests with pytest (using uv to ensure correct environment)
uv run pytest tests/e2e/ -v --tb=short "$@"

TEST_EXIT_CODE=$?

# Step 6: Print container logs on failure
if [ $TEST_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "==> Tests failed! Container logs:"
    docker logs "$CONTAINER_NAME" --tail 100
fi

echo ""
echo "==> Test run completed with exit code: $TEST_EXIT_CODE"

exit $TEST_EXIT_CODE
