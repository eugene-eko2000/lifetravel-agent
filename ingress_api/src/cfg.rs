use clap::Parser;
use eko2000_rustlib::rabbitmq::publisher::Publisher;
use std::sync::Arc;
use tokio::sync::broadcast;

use crate::subscribe::{ProgressData, TripCard};

#[derive(Parser, Debug, Clone)]
#[command(author, version, about, long_about = None)]
pub struct Cfg {
    /// Port to bind the server to
    #[arg(long, env = "PORT", default_value_t = 3000)]
    pub port: u16,

    /// RabbitMQ host
    #[arg(long, env = "AMQP_HOST", default_value = "localhost")]
    pub amqp_host: String,

    /// RabbitMQ port
    #[arg(long, env = "AMQP_PORT", default_value_t = 5672)]
    pub amqp_port: u16,

    /// RabbitMQ user
    #[arg(long, env = "AMQP_USER", default_value = "guest")]
    pub amqp_user: String,

    /// RabbitMQ password
    #[arg(long, env = "AMQP_PASSWORD", default_value = "guest")]
    pub amqp_password: String,

    /// RabbitMQ exchange name
    #[arg(long, env = "RABBITMQ_EXCHANGE", default_value = "prompts")]
    pub rabbitmq_exchange: String,

    /// RabbitMQ routing key
    #[arg(long, env = "RABBITMQ_REQUEST_ROUTING_KEY", default_value = "prompt")]
    pub rabbitmq_request_routing_key: String,

    /// RabbitMQ trip card routing key
    #[arg(
        long,
        env = "RABBITMQ_TRIPCARD_ROUTING_KEY",
        default_value = "tripcard"
    )]
    pub rabbitmq_tripcard_routing_key: String,

    /// RabbitMQ progress message routing key
    #[arg(
        long,
        env = "RABBITMQ_PROGRESS_ROUTING_KEY",
        default_value = "progress"
    )]
    pub rabbitmq_progress_routing_key: String,

    /// RabbitMQ queue name for responses
    #[arg(
        long,
        env = "RABBITMQ_RESPONSE_QUEUE",
        default_value = "response_queue"
    )]
    pub rabbitmq_response_queue: String,
}

impl Cfg {
    /// Composes the RabbitMQ connection URL from the AMQP components
    pub fn rabbitmq_url(&self) -> String {
        format!(
            "amqp://{}:{}@{}:{}",
            self.amqp_user, self.amqp_password, self.amqp_host, self.amqp_port
        )
    }
}

/// Application state containing configuration and RabbitMQ publisher
#[derive(Clone)]
pub struct AppState {
    pub publisher: Arc<Publisher>,
    /// Broadcast channel sender for progress messages from RabbitMQ subscriber
    pub progress_tx: broadcast::Sender<ProgressData>,
    /// Broadcast channel sender for TripCard messages from RabbitMQ subscriber
    pub tripcard_tx: broadcast::Sender<TripCard>,
}
