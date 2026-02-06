use std::sync::Arc;

use eko2000_rustlib::rabbitmq::subscriber::{Callback, Message, Subscriber};
use serde::{Deserialize, Serialize};
use tracing::info;
use uuid::Uuid;

/// Incoming prompt message from the ingress API
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct PromptMessage {
    pub request_id: Uuid,
    pub prompt: String,
}

/// Callback handler for processing incoming prompt messages
pub struct PromptCallback;

impl PromptCallback {
    pub fn new() -> Self {
        Self
    }
}

impl Default for PromptCallback {
    fn default() -> Self {
        Self::new()
    }
}

impl Callback for PromptCallback {
    fn on_message(&self, msg: &Message) -> Result<(), Box<dyn std::error::Error>> {
        let prompt: PromptMessage = serde_json::from_slice(&msg.body)?;
        info!("Received PromptMessage: {:?}", prompt);

        // TODO: Implement agent orchestration logic here
        // 1. Parse the prompt
        // 2. Determine which agents to invoke
        // 3. Coordinate agent execution
        // 4. Aggregate responses
        // 5. Publish results back to RabbitMQ

        Ok(())
    }
}

/// Initialize and start the RabbitMQ subscriber for prompt messages
pub async fn start_subscriber(
    connection_url: &str,
    exchange: &str,
    queue_name: &str,
    routing_key: &str,
) -> anyhow::Result<()> {
    info!("Initializing RabbitMQ subscriber for prompt messages...");

    let callback = PromptCallback::new();

    let subscriber = Subscriber::new(connection_url, exchange, queue_name)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to initialize RabbitMQ subscriber: {}", e))?
        .add_callback(routing_key, Arc::new(callback));

    info!("Successfully initialized RabbitMQ subscriber");
    info!(
        "Subscribed to exchange: {}, queue: {}, routing_key: {}",
        exchange, queue_name, routing_key
    );

    subscriber
        .start()
        .await
        .map_err(|e| anyhow::anyhow!("Failed to start subscriber: {}", e))?;

    Ok(())
}
