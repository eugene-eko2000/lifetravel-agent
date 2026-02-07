use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::info;

// ---------------------------------------------------------------------------
// OpenAI Responses API – request types
// ---------------------------------------------------------------------------

/// A single input message for the Responses API.
#[derive(Serialize, Debug)]
struct InputMessage {
    role: &'static str,
    content: String,
}

/// The `text.format` block that enables Structured Outputs.
#[derive(Serialize, Debug)]
struct TextFormat {
    r#type: &'static str,
    name: &'static str,
    schema: serde_json::Value,
    strict: bool,
}

/// The `text` configuration block of the request body.
#[derive(Serialize, Debug)]
struct TextConfig {
    format: TextFormat,
}

/// Top-level request body for `POST /v1/responses`.
#[derive(Serialize, Debug)]
struct ResponsesRequest {
    model: String,
    instructions: String,
    input: Vec<InputMessage>,
    text: TextConfig,
}

// ---------------------------------------------------------------------------
// OpenAI Responses API – response types
// ---------------------------------------------------------------------------

#[derive(Deserialize, Debug)]
struct ContentItem {
    // r#type: String,
    text: String,
}

#[derive(Deserialize, Debug)]
struct OutputItem {
    // r#type: String,
    content: Vec<ContentItem>,
}

#[derive(Deserialize, Debug)]
struct ResponsesResponse {
    // id: String,
    output: Vec<OutputItem>,
}

// ---------------------------------------------------------------------------
// Domain output – placeholder
// ---------------------------------------------------------------------------

/// Structured output returned by the LLM.
///
/// TODO: Define the actual fields for the trip request.
#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct TripRequest {
    // placeholder – fields will be added later
}

// ---------------------------------------------------------------------------
// Prompts – placeholders
// ---------------------------------------------------------------------------

/// System-level instructions sent via the `instructions` field.
///
/// TODO: Replace with the real system prompt.
const SYSTEM_PROMPT: &str = "You are a helpful travel planning assistant.";

/// Developer prompt prepended to the conversation as a `developer` message.
///
/// TODO: Replace with the real developer prompt.
const DEVELOPER_PROMPT: &str = "";

// ---------------------------------------------------------------------------
// Response format – placeholder
// ---------------------------------------------------------------------------

/// Builds the JSON Schema that describes `TripRequest` for Structured Outputs.
///
/// TODO: Replace with the actual JSON Schema matching `TripRequest` fields.
fn trip_request_schema() -> serde_json::Value {
    serde_json::json!({
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false
    })
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

const OPENAI_RESPONSES_URL: &str = "https://api.openai.com/v1/responses";

/// Calls the OpenAI Responses API with Structured Outputs and returns a
/// [`TripRequest`] parsed from the LLM response.
///
/// # Arguments
/// * `api_key`     – OpenAI API key.
/// * `model`       – Model identifier (e.g. `"gpt-4o"`).
/// * `user_prompt` – The end-user prompt describing the desired trip.
pub async fn get_trip_request(
    api_key: &str,
    model: &str,
    user_prompt: &str,
) -> anyhow::Result<TripRequest> {
    let mut input: Vec<InputMessage> = Vec::new();

    // Developer message (if provided)
    if !DEVELOPER_PROMPT.is_empty() {
        input.push(InputMessage {
            role: "developer",
            content: DEVELOPER_PROMPT.to_string(),
        });
    }

    // User message
    input.push(InputMessage {
        role: "user",
        content: user_prompt.to_string(),
    });

    let body = ResponsesRequest {
        model: model.to_string(),
        instructions: SYSTEM_PROMPT.to_string(),
        input,
        text: TextConfig {
            format: TextFormat {
                r#type: "json_schema",
                name: "trip_request",
                schema: trip_request_schema(),
                strict: true,
            },
        },
    };

    info!("Sending request to OpenAI Responses API (model: {})", model);

    let client = Client::new();
    let response = client
        .post(OPENAI_RESPONSES_URL)
        .bearer_auth(api_key)
        .json(&body)
        .send()
        .await?;

    let status = response.status();
    if !status.is_success() {
        let error_body = response.text().await.unwrap_or_default();
        anyhow::bail!(
            "OpenAI API returned status {}: {}",
            status,
            error_body
        );
    }

    let api_response: ResponsesResponse = response.json().await?;

    // Extract the text content from the first output message
    let text = api_response
        .output
        .first()
        .and_then(|item| item.content.first())
        .map(|c| c.text.as_str())
        .ok_or_else(|| anyhow::anyhow!("No output content in OpenAI response"))?;

    info!("Received structured output from OpenAI");

    let trip_request: TripRequest = serde_json::from_str(text)?;

    Ok(trip_request)
}
