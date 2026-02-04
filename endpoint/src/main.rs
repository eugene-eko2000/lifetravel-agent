use axum::{routing::post, Router};
use clap::Parser;
use tower_http::cors::CorsLayer;
use tracing::info;

mod cfg;
mod handlers;
mod publish;

use crate::{cfg::Cfg, handlers::handle_prompt};

#[tokio::main]
async fn main() {
    // Initialize tracing subscriber
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let args = Cfg::parse();
    let bind_address = format!("0.0.0.0:{}", args.port);

    let app = Router::new()
        .route("/api/v1/prompt", post(handle_prompt))
        .layer(CorsLayer::permissive())
        .with_state(args);
    let listener = tokio::net::TcpListener::bind(&bind_address)
        .await
        .expect("Failed to bind to address");

    info!("Server running on http://{}", bind_address);
    info!(
        "POST endpoint available at http://{}/api/v1/prompt",
        bind_address
    );

    axum::serve(listener, app)
        .await
        .expect("Server failed to start");
}
