use axum::{routing::get, Router};
use clap::Parser;
use std::sync::Arc;
use tracing::info;

mod cfg;
mod handlers;
mod llm;
mod publish;
mod subscribe;

use crate::cfg::Cfg;
use crate::handlers::health;
use crate::subscribe::start_subscriber;
use eko2000_rustlib::rabbitmq::publisher::Publisher;

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

    // Initialize RabbitMQ publisher for progress messages
    info!("Initializing RabbitMQ publisher for progress messages...");
    let progress_publisher = Publisher::new(
        &cfg.rabbitmq_url(),
        &cfg.rabbitmq_exchange,
        &cfg.rabbitmq_progress_routing_key,
    )
    .await
    .map_err(|e| anyhow::anyhow!("Failed to initialize RabbitMQ publisher: {}", e))?;

    let progress_publisher = Arc::new(progress_publisher);
    info!("Successfully initialized RabbitMQ progress publisher");

    // Start the RabbitMQ subscriber (non-blocking)
    start_subscriber(
        &cfg.rabbitmq_url(),
        &cfg.rabbitmq_exchange,
        &cfg.rabbitmq_queue,
        &cfg.rabbitmq_request_routing_key,
        progress_publisher,
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
