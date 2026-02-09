use std::{fmt::Debug, sync::Arc};

use eko2000_rustlib::rabbitmq::subscriber::{Callback, Message, Subscriber};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use tokio::sync::broadcast;
use tracing::{error, info};

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct ProgressData {
    // Empty structure - will be filled with data later
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct TripCard {
    // Empty structure - will be filled with data later
}

pub struct ResponseCallback<T> {
    response_tx: broadcast::Sender<T>,
}

impl<T> ResponseCallback<T> {
    pub fn new(response_tx: broadcast::Sender<T>) -> Self {
        Self { response_tx }
    }
}

impl<T: DeserializeOwned + Clone + Debug + Send + Sync + 'static> Callback for ResponseCallback<T> {
    fn on_message(&self, msg: &Message) -> Result<(), Box<dyn std::error::Error>> {
        let response: T = serde_json::from_slice(&msg.body)?;
        info!("Received response from RabbitMQ: {:?}", response);

        // Send the response to all WebSocket connections via the broadcast channel
        if let Err(e) = self.response_tx.send(response.clone()) {
            error!("Failed to broadcast response (no receivers): {}", e);
        }

        Ok(())
    }
}

pub async fn subscribe_to_agent_responses(
    connection_url: &str,
    exchange: &str,
    queue_name: &str,
    progress_routing_key: &str,
    tripcard_routing_key: &str,
    progress_tx: broadcast::Sender<ProgressData>,
    tripcard_tx: broadcast::Sender<TripCard>,
) -> anyhow::Result<()> {
    info!("Initializing RabbitMQ subscriber for TripCard messages...");

    let progress_callback = Arc::new(ResponseCallback::new(progress_tx));
    let tripcard_callback = Arc::new(ResponseCallback::new(tripcard_tx));

    let subscriber = Subscriber::new(connection_url, exchange, queue_name)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to initialize RabbitMQ subscriber: {}", e))?
        .add_callback(progress_routing_key, progress_callback)
        .add_callback(tripcard_routing_key, tripcard_callback);

    info!("Successfully initialized RabbitMQ subscriber");
    info!(
        "Subscribed to exchange: {}, queue_name: {}, tripcard_routing_key: {}",
        exchange, queue_name, tripcard_routing_key
    );

    subscriber
        .async_start()
        .await
        .map_err(|e| anyhow::anyhow!("Failed to start subscriber: {}", e))?;

    Ok(())
}
