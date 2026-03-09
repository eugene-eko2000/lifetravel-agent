#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Error: docker-compose.yml not found at ${COMPOSE_FILE}" >&2
  exit 1
fi

# Load variables from .env into the current shell environment (if present).
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a
  echo "Loaded environment from ${ENV_FILE}"
else
  echo "Warning: ${ENV_FILE} not found. Using current shell environment only."
fi

# Allow attached mode if explicitly requested.
# Usage:
#   ./run_compose.sh            -> up --build -d
#   ./run_compose.sh --attach   -> up --build
UP_ARGS=(up --build -d)
if [[ "${1:-}" == "--attach" ]]; then
  UP_ARGS=(up --build)
fi

docker compose -f "${COMPOSE_FILE}" "${UP_ARGS[@]}"
