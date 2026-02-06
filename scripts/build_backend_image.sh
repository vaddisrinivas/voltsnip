#!/usr/bin/env bash
set -euo pipefail

REPO=${GITHUB_REPOSITORY:-voltsnip/voltsnip}
IMAGE_NAME=${IMAGE_NAME:-ghcr.io/${REPO}-backend}
IMAGE_TAG=${IMAGE_TAG:-latest}
CONTEXT_DIR=${CONTEXT_DIR:-backend}
DOCKERFILE=${DOCKERFILE:-Dockerfile}

DOCKERFILE_PATH="${CONTEXT_DIR}/${DOCKERFILE}"

docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -f "${DOCKERFILE_PATH}" "${CONTEXT_DIR}"

if [[ "${PUSH_IMAGE:-0}" == "1" ]]; then
  docker push "${IMAGE_NAME}:${IMAGE_TAG}"
fi
