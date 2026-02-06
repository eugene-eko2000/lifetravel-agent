use clap::Parser;
use tracing::{error, info};

mod cfg;
mod subscribe;

use crate::cfg::Cfg;
use crate::subscribe::start_subscriber;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing subscriber
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    info!("Starting Agent Orchestrator Service...");

    let cfg = Cfg::parse();

    info!(
        "Connecting to RabbitMQ at {}:{}",
        cfg.amqp_host, cfg.amqp_port
    );

    // Start the RabbitMQ subscriber (this will block and run indefinitely)
    if let Err(e) = start_subscriber(
        &cfg.rabbitmq_url(),
        &cfg.rabbitmq_exchange,
        &cfg.rabbitmq_queue,
        &cfg.rabbitmq_routing_key,
    )
    .await
    {
        error!("Agent Orchestrator failed: {}", e);
        return Err(e);
    }

    Ok(())
}
