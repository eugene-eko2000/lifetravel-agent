use axum::{extract::State, http::StatusCode, response::Json as ResponseJson, Json};
use serde::{Deserialize, Serialize};
use tracing::{error, info};
use uuid::Uuid;

use crate::cfg::AppState;
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

async fn handle_prompt_internal(
    state: AppState,
    payload: PromptRequest,
) -> anyhow::Result<PromptResponse> {
    if payload.prompt.is_empty() {
        return Err(anyhow::anyhow!("Received empty prompt"));
    }

    // Generate unique request ID
    let request_id = Uuid::new_v4();
    info!("Received prompt with request_id: {}", request_id);
    
    // Publish to RabbitMQ
    if let Err(e) = publish_prompt(
        state.publisher.clone(),
        request_id,
        payload.prompt.clone(),
    )
    .await
    {
        error!("Failed to publish prompt to RabbitMQ: {}", e);
        // Continue anyway - we still return success to the client
    }
    
    Ok(PromptResponse {
        message: "Prompt received successfully".to_string(),
        received_prompt: payload.prompt,
    })
}

pub async fn handle_prompt(
    State(state): State<AppState>,
    Json(payload): Json<PromptRequest>,
) -> Result<ResponseJson<PromptResponse>, StatusCode> {
    match handle_prompt_internal(state, payload).await {
        Ok(response) => Ok(ResponseJson(response)),
        Err(e) => {
            error!("Error handling prompt: {}", e);
            Err(StatusCode::BAD_REQUEST)
        }
    }
}
