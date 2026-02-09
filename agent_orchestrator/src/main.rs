use axum::{routing::get, Router};
use clap::Parser;
use tracing::info;

mod cfg;
mod handlers;
mod llm;
mod subscribe;

use crate::cfg::Cfg;
use crate::handlers::health;
use crate::subscribe::start_subscriber;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing subscriber
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    info!("Starting Agent Orchestrator Service...");

    let cfg = Cfg::parse();
    let bind_address = format!("0.0.0.0:{}", cfg.port);

    info!(
        "Connecting to RabbitMQ at {}:{}",
        cfg.amqp_host, cfg.amqp_port
    );

    // Start the RabbitMQ subscriber (non-blocking)
    start_subscriber(
        &cfg.rabbitmq_url(),
        &cfg.rabbitmq_exchange,
        &cfg.rabbitmq_queue,
        &cfg.rabbitmq_request_routing_key,
    )
    .await?;

    // Build the Axum router
    let app = Router::new().route("/health", get(health));

    // Start the HTTP server
    let listener = tokio::net::TcpListener::bind(&bind_address)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to bind to {}: {}", bind_address, e))?;

    info!("HTTP server listening on http://{}", bind_address);

    axum::serve(listener, app)
        .await
        .map_err(|e| anyhow::anyhow!("HTTP server failed: {}", e))?;

    Ok(())
}
