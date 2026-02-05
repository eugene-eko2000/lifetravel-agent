use axum::{
    extract::{State, ws::{WebSocket, Message, WebSocketUpgrade}},
    response::Response,
};
use serde::{Deserialize, Serialize};
use tracing::{error, info, warn};
use uuid::Uuid;
use futures_util::{SinkExt, StreamExt};

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
    request_id: String,
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
        request_id: request_id.to_string(),
    })
}

async fn handle_socket(state: AppState, socket: WebSocket) {
    let (mut sender, mut receiver) = socket.split();

    while let Some(msg) = receiver.next().await {
        match msg {
            Ok(Message::Text(text)) => {
                info!("Received WebSocket message: {}", text);
                
                // Parse JSON request
                let request: PromptRequest = match serde_json::from_str(&text) {
                    Ok(req) => req,
                    Err(e) => {
                        error!("Failed to parse request: {}", e);
                        let error_response = serde_json::json!({
                            "error": format!("Invalid request format: {}", e)
                        });
                        if let Err(e) = sender.send(Message::Text(serde_json::to_string(&error_response).unwrap_or_default())).await {
                            error!("Failed to send error response: {}", e);
                            break;
                        }
                        continue;
                    }
                };

                // Process the prompt
                match handle_prompt_internal(state.clone(), request).await {
                    Ok(response) => {
                        let response_json = match serde_json::to_string(&response) {
                            Ok(json) => json,
                            Err(e) => {
                                error!("Failed to serialize response: {}", e);
                                continue;
                            }
                        };
                        
                        if let Err(e) = sender.send(Message::Text(response_json)).await {
                            error!("Failed to send response: {}", e);
                            break;
                        }
                    }
                    Err(e) => {
                        error!("Error handling prompt: {}", e);
                        let error_response = serde_json::json!({
                            "error": e.to_string()
                        });
                        if let Err(e) = sender.send(Message::Text(serde_json::to_string(&error_response).unwrap_or_default())).await {
                            error!("Failed to send error response: {}", e);
                            break;
                        }
                    }
                }
            }
            Ok(Message::Close(_)) => {
                info!("WebSocket connection closed by client");
                break;
            }
            Ok(Message::Ping(data)) => {
                if let Err(e) = sender.send(Message::Pong(data)).await {
                    error!("Failed to send pong: {}", e);
                    break;
                }
            }
            Ok(_) => {
                warn!("Received unsupported WebSocket message type");
            }
            Err(e) => {
                error!("WebSocket error: {}", e);
                break;
            }
        }
    }
    
    info!("WebSocket connection ended");
}

pub async fn handle_websocket(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.on_upgrade(|socket| handle_socket(state, socket))
}
