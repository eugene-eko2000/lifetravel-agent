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

# Usage:
#   ./run_compose.sh                 -> up --build -d
#   ./run_compose.sh --attach        -> up --build (foreground)
#   ./run_compose.sh --rerun         -> up --build -d --force-recreate (recreate all containers)
#   ./run_compose.sh --attach --rerun
ATTACH=false
RERUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --attach)
      ATTACH=true
      ;;
    --rerun)
      RERUN=true
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--attach] [--rerun]" >&2
      exit 1
      ;;
  esac
  shift
done

UP_ARGS=(up --build -d)
if [[ "${ATTACH}" == true ]]; then
  UP_ARGS=(up --build)
fi
if [[ "${RERUN}" == true ]]; then
  UP_ARGS+=(--force-recreate)
fi

docker compose -f "${COMPOSE_FILE}" "${UP_ARGS[@]}"
