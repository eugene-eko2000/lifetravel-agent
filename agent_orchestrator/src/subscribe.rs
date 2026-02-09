use std::sync::Arc;

use eko2000_rustlib::rabbitmq::{publisher::Publisher, subscriber::{Callback, Message, Subscriber}};
use serde::{Deserialize, Serialize};
use tokio::spawn;
use tracing::{error, info};
use uuid::Uuid;

use crate::publish::{ProgressData, ProgressStatus, publish_progress};

/// Incoming prompt message from the ingress API
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct PromptMessage {
    pub request_id: Uuid,
    pub prompt: String,
}

/// Callback handler for processing incoming prompt messages
pub struct PromptCallback {
    progress_publisher: Arc<Publisher>,
}

impl PromptCallback {
    pub fn new(progress_publisher: Arc<Publisher>) -> Self {
        Self { progress_publisher }
    }
}

impl Callback for PromptCallback {
    fn on_message(&self, msg: &Message) -> anyhow::Result<()> {
        let prompt: PromptMessage = serde_json::from_slice(&msg.body)?;
        let progress_publisher = self.progress_publisher.clone();
        spawn(async move {
            publish_progress(progress_publisher, ProgressData {
                status: ProgressStatus::SingleEvent,
                message: format!("Received prompt with request_id: {}", prompt.request_id),
            }).await
            .unwrap_or_else(|e| {
                error!("Failed to publish progress message: {}", e);
            });
        });
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
    progress_publisher: Arc<Publisher>,
) -> anyhow::Result<()> {
    info!("Initializing RabbitMQ subscriber for prompt messages...");

    let callback = PromptCallback::new(progress_publisher);

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
        .async_start()
        .await
        .map_err(|e| anyhow::anyhow!("Failed to start subscriber: {}", e))?;

    Ok(())
}
