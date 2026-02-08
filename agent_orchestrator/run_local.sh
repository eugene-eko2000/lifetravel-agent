#!/usr/bin/env bash
set -euo pipefail

# ── Shared variables (fallback defaults when running standalone) ─────────────
export AMQP_HOST="${AMQP_HOST:-localhost}"
export AMQP_PORT="${AMQP_PORT:-5672}"
export AMQP_USER="${AMQP_USER:-guest}"
export AMQP_PASSWORD="${AMQP_PASSWORD:-guest}"
export RABBITMQ_EXCHANGE="${RABBITMQ_EXCHANGE:-lifetravel_exchange}"
export RABBITMQ_REQUEST_ROUTING_KEY="${RABBITMQ_REQUEST_ROUTING_KEY:-key.triprequest}"

# ── Agent Orchestrator specific ──────────────────────────────────────────────
export RABBITMQ_QUEUE="${RABBITMQ_QUEUE:-orchestrator_queue}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-$(cat ~/.openai/devapikey)}"
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-5.2}"

cargo run
