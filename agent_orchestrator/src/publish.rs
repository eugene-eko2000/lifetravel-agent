use eko2000_rustlib::rabbitmq::publisher::Publisher;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::info;

/// Status of a progress event.
#[derive(Deserialize, Serialize, Debug, Clone)]
pub enum ProgressStatus {
    SingleEvent,
    InProgress,
    Finished,
}

/// Progress data published to RabbitMQ for the ingress API to forward to clients.
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct ProgressData {
    pub status: ProgressStatus,
    pub message: String,
}

pub async fn publish_progress(
    publisher: Arc<Publisher>,
    progress: ProgressData,
) -> anyhow::Result<()> {
    info!("Publishing progress message to RabbitMQ: {:?}", progress);

    publisher
        .publish(&progress)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to publish progress message: {}", e))?;

    info!("Successfully published progress message to RabbitMQ");
    Ok(())
}
