use serde::Serialize;
use tracing::info;
use eko2000_rustlib::rabbitmq::publisher::Publisher;

#[derive(Serialize)]
pub struct PromptMessage {
    prompt: String,
}

pub async fn publish_prompt(
    connection_url: &str,
    exchange: &str,
    routing_key: &str,
    prompt: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let message = PromptMessage { prompt };
    
    info!("Publishing prompt to RabbitMQ exchange: {}, routing_key: {}", exchange, routing_key);
    
    let publisher = Publisher::new(connection_url, exchange, routing_key).await?;
    publisher.publish(&message).await?;
    
    info!("Successfully published prompt to RabbitMQ");
    Ok(())
}
