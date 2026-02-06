use std::sync::Arc;

use eko2000_rustlib::rabbitmq::subscriber::{Callback, Message, Subscriber};
use serde::Deserialize;
use tracing::info;

#[derive(Deserialize, Debug, Clone)]
pub struct TripCard {
    // Empty structure - will be filled with data later
}

pub struct ResponseCallback;

impl Callback for ResponseCallback {
    fn on_message(&self, msg: &Message) -> Result<(), Box<dyn std::error::Error>> {
        let trip_card: TripCard = serde_json::from_slice(&msg.body)?;
        handle_trip_card(trip_card)?;
        Ok(())
    }
}

pub async fn subscribe_to_trip_cards(
    connection_url: &str,
    exchange: &str,
    queue_name: &str,
    routing_key: &str,
) -> anyhow::Result<()> {
    info!("Initializing RabbitMQ subscriber for ItineraryCard messages...");

    let subscriber = Subscriber::new(connection_url, exchange, queue_name)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to initialize RabbitMQ subscriber: {}", e))?
        .add_callback(routing_key, Arc::new(ResponseCallback));

    info!("Successfully initialized RabbitMQ subscriber");
    info!(
        "Subscribed to exchange: {}, queue_name: {}",
        exchange, queue_name
    );

    subscriber
        .start()
        .await
        .map_err(|e| anyhow::anyhow!("Failed to start subscriber: {}", e))?;

    Ok(())
}

pub fn handle_trip_card(card: TripCard) -> anyhow::Result<()> {
    info!("Processing TripCard: {:?}", card);
    // Processing logic will be added later
    Ok(())
}
