use eko2000_rustlib::rabbitmq::publisher::Publisher;
use serde::Serialize;
use std::sync::Arc;
use tracing::info;
use uuid::Uuid;

#[derive(Serialize)]
pub struct PromptMessage {
    request_id: Uuid,
    prompt: String,
}

pub async fn publish_prompt(
    publisher: Arc<Publisher>,
    request_id: Uuid,
    prompt: String,
) -> anyhow::Result<()> {
    let message = PromptMessage { request_id, prompt };

    info!(
        "Publishing prompt to RabbitMQ with request_id: {}",
        request_id
    );

    publisher
        .publish(&message)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to publish message: {}", e))?;

    info!("Successfully published prompt to RabbitMQ");
    Ok(())
}
