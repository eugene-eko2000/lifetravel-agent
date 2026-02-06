use std::sync::Arc;

use eko2000_rustlib::rabbitmq::subscriber::{Callback, Message, Subscriber};
use serde::{Deserialize, Serialize};
use tokio::sync::broadcast;
use tracing::{error, info};

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct TripCard {
    // Empty structure - will be filled with data later
}

pub struct ResponseCallback {
    trip_card_tx: broadcast::Sender<TripCard>,
}

impl ResponseCallback {
    pub fn new(trip_card_tx: broadcast::Sender<TripCard>) -> Self {
        Self { trip_card_tx }
    }
}

impl Callback for ResponseCallback {
    fn on_message(&self, msg: &Message) -> Result<(), Box<dyn std::error::Error>> {
        let trip_card: TripCard = serde_json::from_slice(&msg.body)?;
        info!("Received TripCard from RabbitMQ: {:?}", trip_card);
        
        // Send the TripCard to all WebSocket connections via the broadcast channel
        if let Err(e) = self.trip_card_tx.send(trip_card.clone()) {
            error!("Failed to broadcast TripCard (no receivers): {}", e);
        }
        
        Ok(())
    }
}

pub async fn subscribe_to_trip_cards(
    connection_url: &str,
    exchange: &str,
    queue_name: &str,
    routing_key: &str,
    trip_card_tx: broadcast::Sender<TripCard>,
) -> anyhow::Result<()> {
    info!("Initializing RabbitMQ subscriber for TripCard messages...");

    let callback = ResponseCallback::new(trip_card_tx);
    
    let subscriber = Subscriber::new(connection_url, exchange, queue_name)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to initialize RabbitMQ subscriber: {}", e))?
        .add_callback(routing_key, Arc::new(callback));

    info!("Successfully initialized RabbitMQ subscriber");
    info!(
        "Subscribed to exchange: {}, queue_name: {}, routing_key: {}",
        exchange, queue_name, routing_key
    );

    subscriber
        .start()
        .await
        .map_err(|e| anyhow::anyhow!("Failed to start subscriber: {}", e))?;

    Ok(())
}
