#!/usr/bin/env bash
set -euo pipefail

# ── Shared variables (fallback defaults when running standalone) ─────────────
export AMQP_HOST="${AMQP_HOST:-localhost}"
export AMQP_PORT="${AMQP_PORT:-5672}"
export AMQP_USER="${AMQP_USER:-guest}"
export AMQP_PASSWORD="${AMQP_PASSWORD:-guest}"
export RABBITMQ_EXCHANGE="${RABBITMQ_EXCHANGE:-lifetravel_exchange}"
export RABBITMQ_REQUEST_ROUTING_KEY="${RABBITMQ_REQUEST_ROUTING_KEY:-key.triprequest}"

# ── Ingress API specific ────────────────────────────────────────────────────
export PORT="${INGRESS_API_PORT:-8091}"
export RABBITMQ_RESPONSE_ROUTING_KEY="${RABBITMQ_RESPONSE_ROUTING_KEY:-key.tripcard}"
export RABBITMQ_RESPONSE_QUEUE="${RABBITMQ_RESPONSE_QUEUE:-tripcard_queue}"

cargo run
