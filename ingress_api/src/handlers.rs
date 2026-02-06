use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    response::Response,
};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::select;
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::cfg::AppState;
use crate::publish::publish_prompt;
use crate::subscribe::TripCard;

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

#[derive(Serialize)]
pub struct TripCardMessage {
    #[serde(rename = "type")]
    msg_type: String,
    data: TripCard,
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
    if let Err(e) =
        publish_prompt(state.publisher.clone(), request_id, payload.prompt.clone()).await
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

    // Subscribe to TripCard broadcasts
    let mut trip_card_rx = state.trip_card_tx.subscribe();

    loop {
        select! {
            // Handle incoming WebSocket messages from client
            msg = receiver.next() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
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
                    Some(Ok(Message::Close(_))) => {
                        info!("WebSocket connection closed by client");
                        break;
                    }
                    Some(Ok(Message::Ping(data))) => {
                        if let Err(e) = sender.send(Message::Pong(data)).await {
                            error!("Failed to send pong: {}", e);
                            break;
                        }
                    }
                    Some(Ok(_)) => {
                        warn!("Received unsupported WebSocket message type");
                    }
                    Some(Err(e)) => {
                        error!("WebSocket error: {}", e);
                        break;
                    }
                    None => {
                        info!("WebSocket stream ended");
                        break;
                    }
                }
            }

            // Handle TripCard messages from RabbitMQ subscriber
            trip_card = trip_card_rx.recv() => {
                match trip_card {
                    Ok(card) => {
                        info!("Forwarding TripCard to WebSocket client: {:?}", card);

                        let message = TripCardMessage {
                            msg_type: "trip_card".to_string(),
                            data: card,
                        };

                        match serde_json::to_string(&message) {
                            Ok(json) => {
                                if let Err(e) = sender.send(Message::Text(json)).await {
                                    error!("Failed to send TripCard to WebSocket: {}", e);
                                    break;
                                }
                            }
                            Err(e) => {
                                error!("Failed to serialize TripCard message: {}", e);
                            }
                        }
                    }
                    Err(e) => {
                        error!("Error receiving TripCard from broadcast: {}", e);
                        // Don't break - just continue, the channel might recover
                    }
                }
            }
        }
    }

    info!("WebSocket connection ended");
}

pub async fn handle_websocket(ws: WebSocketUpgrade, State(state): State<AppState>) -> Response {
    ws.on_upgrade(|socket| handle_socket(state, socket))
}
