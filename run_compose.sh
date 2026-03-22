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

# Amadeus: full URLs for docker-compose (override any var in .env, or set AMADEUS_BASE_URL only).
AMADEUS_BASE_URL="${AMADEUS_BASE_URL:-https://test.api.amadeus.com}"
AMADEUS_BASE_URL="${AMADEUS_BASE_URL%/}"
export AMADEUS_FLIGHTS_OFFERS_URL="${AMADEUS_FLIGHTS_OFFERS_URL:-${AMADEUS_BASE_URL}/v2/shopping/flight-offers}"
export AMADEUS_TOKEN_URL="${AMADEUS_TOKEN_URL:-${AMADEUS_BASE_URL}/v1/security/oauth2/token}"
export AMADEUS_HOTELS_LIST_URL="${AMADEUS_HOTELS_LIST_URL:-${AMADEUS_BASE_URL}/v1/reference-data/locations/hotels/by-city}"
export AMADEUS_HOTELS_LIST_BY_GEOCODE_URL="${AMADEUS_HOTELS_LIST_BY_GEOCODE_URL:-${AMADEUS_BASE_URL}/v1/reference-data/locations/hotels/by-geocode}"
export AMADEUS_HOTELS_OFFERS_URL="${AMADEUS_HOTELS_OFFERS_URL:-${AMADEUS_BASE_URL}/v3/shopping/hotel-offers}"

# OpenAI API base (query_router, itinerary_verifier)
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.openai.com/v1}"

# Usage:
#   ./run_compose.sh                 -> up --build -d
#   ./run_compose.sh --attach        -> up --build (foreground)
#   ./run_compose.sh --rerun         -> up --build -d --force-recreate (recreate all containers)
#   ./run_compose.sh --attach --rerun
#
# Amadeus/OpenAI service URLs are exported above; use this script before docker compose so
# compose receives AMADEUS_*_URL, AMADEUS_TOKEN_URL, and OPENAI_BASE_URL. Override via .env
# (e.g. AMADEUS_BASE_URL or individual AMADEUS_FLIGHTS_OFFERS_URL).
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
