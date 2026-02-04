use serde::Serialize;
use tracing::info;
use std::sync::Arc;
use eko2000_rustlib::rabbitmq::publisher::Publisher;

#[derive(Serialize)]
pub struct PromptMessage {
    prompt: String,
}

pub async fn publish_prompt(
    publisher: Arc<Publisher>,
    prompt: String,
) -> anyhow::Result<()> {
    let message = PromptMessage { prompt };
    
    info!("Publishing prompt to RabbitMQ");
    
    publisher.publish(&message).await
        .map_err(|e| anyhow::anyhow!("Failed to publish message: {}", e))?;
    
    info!("Successfully published prompt to RabbitMQ");
    Ok(())
}
