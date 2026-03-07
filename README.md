# Lifetravel Agent

## Data Message Schemas

This section documents the JSON message contracts currently used between services.

### 1) User Request Message

Message consumed by `query_router` from RabbitMQ.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "UserRequestMessage",
  "type": "object",
  "required": ["content"],
  "properties": {
    "id": {
      "type": "string",
      "description": "Optional request id. If missing, query_router generates UUID."
    },
    "prompt_id": {
      "type": ["string", "null"],
      "description": "Optional previous response id for LLM context."
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "description": "Raw user query text."
    }
  },
  "additionalProperties": true
}
```

### 2) Structured Request Produced by LLM

Object returned by `query_router.llm_client.request_structured_itinerary(...)`
and published as `payload.structured_response`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "StructuredLLMResponse",
  "type": "object",
  "required": ["request_id", "prompt_id", "type", "output"],
  "properties": {
    "request_id": { "type": "string" },
    "prompt_id": { "type": "string" },
    "type": {
      "type": "string",
      "enum": ["valid_request", "missing_info"]
    },
    "output": {
      "oneOf": [
        {
          "type": "object",
          "required": ["trip", "budgets", "confidence"],
          "properties": {
            "trip": {
              "type": "object",
              "required": ["timezone", "legs"],
              "properties": {
                "timezone": { "type": "string" },
                "travelers": { "type": "integer" },
                "legs": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "required": ["from", "to", "depart_date"],
                    "properties": {
                      "from": { "type": "string" },
                      "to": { "type": "string" },
                      "depart_date": { "type": "string", "format": "date" },
                      "depart_time_window": {
                        "type": "object",
                        "properties": {
                          "earliest": { "type": "string", "format": "time" },
                          "latest": { "type": "string", "format": "time" }
                        }
                      }
                    }
                  }
                },
                "stays": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "required": ["check_in", "check_out"],
                    "properties": {
                      "city": { "type": "string" },
                      "city_code": { "type": "string" },
                      "location_latlng": {
                        "type": "object",
                        "required": ["lat", "lng"],
                        "properties": {
                          "lat": { "type": "number" },
                          "lng": { "type": "number" }
                        }
                      },
                      "check_in": { "type": "string", "format": "date" },
                      "check_out": { "type": "string", "format": "date" },
                      "min_rooms": { "type": "integer" }
                    }
                  }
                }
              }
            },
            "budgets": {
              "type": "object",
              "properties": {
                "flights": {
                  "type": "object",
                  "properties": {
                    "amount": { "type": "number" },
                    "currency": { "type": "string" },
                    "scope": { "enum": ["total_trip", "per_leg"] }
                  }
                },
                "hotels": {
                  "type": "object",
                  "properties": {
                    "amount": { "type": "number" },
                    "currency": { "type": "string" },
                    "scope": { "enum": ["per_night", "total_trip"] }
                  }
                }
              }
            },
            "assumptions": {
              "type": "array",
              "items": { "type": "string" }
            },
            "missing_fields": {
              "type": "array",
              "items": { "type": "string" }
            },
            "confidence": { "type": "number" }
          }
        },
        {
          "type": "object",
          "required": ["missing_info"],
          "properties": {
            "missing_info": { "type": "string" }
          }
        }
      ]
    }
  },
  "additionalProperties": true
}
```

### 3) Itinerary Flight & Hotel Response Message

Output produced by `inventory_service.request_processor.process_incoming_message(...)`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ItineraryInventoryResponse",
  "type": "object",
  "required": ["flights", "hotels"],
  "properties": {
    "flights": {
      "type": "array",
      "description": "Raw/normalized flight offers responses from Amadeus."
    },
    "hotels": {
      "type": "object",
      "description": "Map of check-in date -> list of available hotel suggestions.",
      "additionalProperties": {
        "type": "array",
        "items": {
          "type": "object"
        }
      }
    }
  },
  "additionalProperties": false
}
```

## Message Routing Table

`exchange name` is configurable via `RABBITMQ_EXCHANGE` (default: `lifetravel_agent`) in all services.

| exchange name | routing key | message name | publishers services list | subscribers services list |
| --- | --- | --- | --- | --- |
| `lifetravel_agent` | `itinerary:user_request` | `UserRequestMessage` | `endpoint_api` | `query_router` |
| `lifetravel_agent` | `itinerary:structured_request` | `StructuredLLMResponse` | `query_router` | `inventory_service` |
| `lifetravel_agent` | `itinerary:missing_info` | `MissingInfoMessage` (`structured_response.type = "missing_info"`) | `query_router` | _(no subscriber currently implemented)_ |
