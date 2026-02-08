use clap::Parser;

#[derive(Parser, Debug, Clone)]
#[command(author, version, about = "Agent Orchestrator Service", long_about = None)]
pub struct Cfg {
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

    /// RabbitMQ queue name for incoming prompts
    #[arg(long, env = "RABBITMQ_QUEUE", default_value = "orchestrator_queue")]
    pub rabbitmq_queue: String,

    /// RabbitMQ routing key for incoming prompts
    #[arg(long, env = "RABBITMQ_ROUTING_KEY", default_value = "prompt")]
    pub rabbitmq_routing_key: String,

    /// OpenAI API key
    #[arg(long, env = "OPENAI_API_KEY")]
    pub openai_api_key: String,

    /// OpenAI model to use
    #[arg(long, env = "OPENAI_MODEL", default_value = "gpt-5.2")]
    pub openai_model: String,
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
