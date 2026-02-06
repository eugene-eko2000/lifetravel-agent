use axum::{routing::get, Router};
use clap::Parser;
use tower_http::cors::CorsLayer;
use tracing::{info, error};
use std::sync::Arc;
use tokio::sync::broadcast;

mod cfg;
mod handlers;
mod publish;
mod subscribe;

use crate::{cfg::{Cfg, AppState}, handlers::handle_websocket};
use crate::subscribe::subscribe_to_trip_cards;
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
    let (trip_card_tx, _) = broadcast::channel(100);

    // Create application state
    let app_state = AppState {
        publisher,
        trip_card_tx: trip_card_tx.clone(),
    };

    // Start the RabbitMQ subscriber in a background task
    let subscriber_cfg = cfg.clone();
    let subscriber_tx = trip_card_tx.clone();
    tokio::spawn(async move {
        info!("Starting RabbitMQ subscriber for TripCard messages...");
        if let Err(e) = subscribe_to_trip_cards(
            &subscriber_cfg.rabbitmq_url(),
            &subscriber_cfg.rabbitmq_exchange,
            &subscriber_cfg.rabbitmq_response_queue,
            &subscriber_cfg.rabbitmq_response_routing_key,
            subscriber_tx,
        )
        .await
        {
            error!("RabbitMQ subscriber failed: {}", e);
        }
    });

    let app = Router::new()
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
