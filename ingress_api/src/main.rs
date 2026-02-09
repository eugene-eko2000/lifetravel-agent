use axum::{routing::get, Router};
use clap::Parser;
use std::sync::Arc;
use tokio::sync::broadcast;
use tower_http::cors::CorsLayer;
use tracing::{error, info};

mod cfg;
mod handlers;
mod publish;
mod subscribe;

use crate::subscribe::subscribe_to_agent_responses;
use crate::{
    cfg::{AppState, Cfg},
    handlers::{handle_websocket, health},
};
use eko2000_rustlib::rabbitmq::publisher::Publisher;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing subscriber
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let cfg = Cfg::parse();
    let bind_address = format!("0.0.0.0:{}", cfg.port);

    // Initialize RabbitMQ publisher once at startup
    info!("Initializing RabbitMQ publisher...");
    let publisher = Publisher::new(
        &cfg.rabbitmq_url(),
        &cfg.rabbitmq_exchange,
        &cfg.rabbitmq_request_routing_key,
    )
    .await
    .map_err(|e| anyhow::anyhow!("Failed to initialize RabbitMQ publisher: {}", e))?;

    info!("Successfully initialized RabbitMQ publisher");
    let publisher = Arc::new(publisher);

    // Create broadcast channel for TripCard messages (capacity of 100 messages)
    let (tripcard_tx, _) = broadcast::channel(100);
    // Create broadcast channel for ProgressData messages (capacity of 100 messages)
    let (progress_tx, _) = broadcast::channel(100);

    // Create application state
    let app_state = AppState {
        publisher,
        tripcard_tx: tripcard_tx.clone(),
        progress_tx: progress_tx.clone(),
    };

    // Start the RabbitMQ subscriber in a background task
    let subscriber_cfg = cfg.clone();
    let progress_tx = progress_tx.clone();
    let tripcard_tx = tripcard_tx.clone();
    tokio::spawn(async move {
        info!("Starting RabbitMQ subscriber for TripCard messages...");
        if let Err(e) = subscribe_to_agent_responses(
            &subscriber_cfg.rabbitmq_url(),
            &subscriber_cfg.rabbitmq_exchange,
            &subscriber_cfg.rabbitmq_response_queue,
            &subscriber_cfg.rabbitmq_progress_routing_key,
            &subscriber_cfg.rabbitmq_tripcard_routing_key,
            progress_tx,
            tripcard_tx,
        )
        .await
        {
            error!("RabbitMQ subscriber failed: {}", e);
        }
    });

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/v1/prompt", get(handle_websocket))
        .layer(CorsLayer::permissive())
        .with_state(app_state);

    let listener = tokio::net::TcpListener::bind(&bind_address)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to bind to address {}: {}", bind_address, e))?;

    info!("Server running on ws://{}", bind_address);
    info!(
        "WebSocket endpoint available at ws://{}/api/v1/prompt",
        bind_address
    );

    axum::serve(listener, app)
        .await
        .map_err(|e| anyhow::anyhow!("Server failed to start: {}", e))?;

    Ok(())
}
