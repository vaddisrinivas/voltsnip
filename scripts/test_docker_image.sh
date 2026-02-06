#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
REPO=${GITHUB_REPOSITORY:-voltsnip/voltsnip}
IMAGE_NAME=${IMAGE_NAME:-ghcr.io/${REPO}-backend}
IMAGE_TAG=${IMAGE_TAG:-latest}
PORT=${DOCKER_TEST_PORT:-18000}
CONTAINER_NAME="voltsnip-backend-test-${RANDOM}"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! docker image inspect "${IMAGE_NAME}:${IMAGE_TAG}" >/dev/null 2>&1; then
  echo "Docker image not found: ${IMAGE_NAME}:${IMAGE_TAG}" >&2
  exit 1
fi

# Provide a valid-looking DATABASE_URL to satisfy settings.
DB_URL=${DATABASE_URL:-"postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/postgres"}

docker run --rm -d \
  --name "$CONTAINER_NAME" \
  -p "${PORT}:8000" \
  -e DATABASE_URL="$DB_URL" \
  "${IMAGE_NAME}:${IMAGE_TAG}" >/dev/null

# Wait for /health
for i in {1..30}; do
  if curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    echo "Docker image health OK"
    exit 0
  fi
  sleep 1
  if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Container exited before health check passed" >&2
    exit 1
  fi
  if [[ $i -eq 30 ]]; then
    echo "Timed out waiting for /health" >&2
    exit 1
  fi
done
