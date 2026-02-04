use axum::{extract::State, http::StatusCode, response::Json as ResponseJson, Json};
use serde::{Deserialize, Serialize};
use tracing::{error, info};

use crate::cfg::Cfg;
use crate::publish::publish_prompt;

#[derive(Deserialize)]
pub struct PromptRequest {
    prompt: String,
}

#[derive(Serialize)]
pub struct PromptResponse {
    message: String,
    received_prompt: String,
}

pub async fn handle_prompt(
    State(args): State<Cfg>,
    Json(payload): Json<PromptRequest>,
) -> Result<ResponseJson<PromptResponse>, StatusCode> {
    if payload.prompt.is_empty() {
        error!("Received empty prompt");
        return Err(StatusCode::BAD_REQUEST);
    }

    info!("Received prompt: {}", payload.prompt);
    
    // Publish to RabbitMQ
    if let Err(e) = publish_prompt(
        &args.rabbitmq_url(),
        &args.rabbitmq_exchange,
        &args.rabbitmq_routing_key,
        payload.prompt.clone(),
    )
    .await
    {
        error!("Failed to publish prompt to RabbitMQ: {}", e);
        // Continue anyway - we still return success to the client
    }
    
    Ok(ResponseJson(PromptResponse {
        message: "Prompt received successfully".to_string(),
        received_prompt: payload.prompt,
    }))
}
