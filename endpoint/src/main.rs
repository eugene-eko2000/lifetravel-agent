use axum::{routing::post, Router};
use clap::Parser;
use tower_http::cors::CorsLayer;
use tracing::info;
use std::sync::Arc;

mod cfg;
mod handlers;
mod publish;

use crate::{cfg::{Cfg, AppState}, handlers::handle_prompt};
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
        &cfg.rabbitmq_routing_key,
    )
    .await
    .map_err(|e| anyhow::anyhow!("Failed to initialize RabbitMQ publisher: {}", e))?;
    
    info!("Successfully initialized RabbitMQ publisher");
    let publisher = Arc::new(publisher);

    // Create application state
    let app_state = AppState {
        cfg,
        publisher,
    };

    let app = Router::new()
        .route("/api/v1/prompt", post(handle_prompt))
        .layer(CorsLayer::permissive())
        .with_state(app_state);
    
    let listener = tokio::net::TcpListener::bind(&bind_address)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to bind to address {}: {}", bind_address, e))?;

    info!("Server running on http://{}", bind_address);
    info!(
        "POST endpoint available at http://{}/api/v1/prompt",
        bind_address
    );

    axum::serve(listener, app)
        .await
        .map_err(|e| anyhow::anyhow!("Server failed to start: {}", e))?;
    
    Ok(())
}
