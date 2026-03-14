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
and published as `payload.structured_request`.

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
      "const": ["valid_request"]
    },
    "output": {
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
                  },
                  "arrive_date": { "type": "string", "format": "date", "description": "Optional flight arrival date (e.g. for stay alignment)." },
                  "arrive_time_window": {
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
    }
  },
  "additionalProperties": true
}
```

### 3) Itinerary Flight & Hotel Response Message

Output produced by `inventory_hotel_service.request_processor.process_incoming_message(...)`.
Hotels are grouped by stay date range per itinerary.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ItineraryInventoryResponse",
  "type": "object",
  "required": ["itineraries"],
  "properties": {
    "itineraries": {
      "type": "array",
      "description": "One entry per flight offer; each has flight and hotels by stay period.",
      "items": {
        "type": "object",
        "required": ["flight", "hotels"],
        "properties": {
          "flight": {
            "type": "object",
            "description": "Single Amadeus flight offer (with itineraries, etc.)."
          },
          "hotels": {
            "type": "object",
            "description": "Map of stay period '<date-begin - date-end>' to list of hotel offers.",
            "additionalProperties": {
              "type": "array",
              "items": { "type": "object" }
            }
          }
        }
      }
    }
  },
  "additionalProperties": false
}
```

### 4) MissingInfoMessage

Message published by `query_router` when the LLM cannot build a complete itinerary request
and consumed by `endpoint_api` subscriber/websocket bridge.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "MissingInfoMessage",
  "type": "object",
  "required": ["id", "content", "structured_request"],
  "properties": {
    "id": {
      "type": "string",
      "description": "Request correlation id."
    },
    "content": {
      "type": "string",
      "description": "Original user prompt content."
    },
    "structured_request": {
      "type": "object",
      "required": ["request_id", "prompt_id", "type", "output"],
      "properties": {
        "request_id": { "type": "string" },
        "prompt_id": { "type": "string" },
        "type": {
          "type": "string",
          "const": "missing_info"
        },
        "output": {
          "type": "object",
          "required": ["missing_info"],
          "properties": {
            "missing_info": { "type": "string" }
          }
        }
      },
      "additionalProperties": true
    }
  },
  "additionalProperties": true
}
```

### 5) DebugMessage

Message consumed by `endpoint_api` debug subscriber and forwarded to the websocket
request owner (correlated by request id). Current publishers use:
- `query_router` with `level = "debug"`
- `inventory_flight_service` and `inventory_hotel_service` (Amadeus send failures) with `level = "error"`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DebugMessage",
  "type": "object",
  "required": ["level", "source", "message"],
  "properties": {
    "id": {
      "type": "string",
      "description": "Primary request correlation id."
    },
    "request_id": {
      "type": "string",
      "description": "Fallback request correlation id when `id` is not set."
    },
    "message": {
      "type": "string",
      "description": "Debug text shown to the client."
    },
    "source": {
      "type": "string",
      "description": "Optional source service/component."
    },
    "level": {
      "type": "string",
      "description": "Severity level of the message.",
      "enum": ["debug", "info", "warning", "error"]
    },
    "payload": {
      "type": "object",
      "description": "Optional extra structured debug details."
    }
  },
  "oneOf": [
    { "required": ["id"] },
    { "required": ["request_id"] }
  ],
  "additionalProperties": true
}
```

## Message Routing Table

`exchange name` is configurable via `RABBITMQ_EXCHANGE` (default: `lifetravel_agent`) in all services.

| exchange name | routing key | message name | publishers services list | subscribers services list |
| --- | --- | --- | --- | --- |
| `lifetravel_agent` | `itinerary:user_request` | `UserRequestMessage` | `endpoint_api` | `query_router` |
| `lifetravel_agent` | `itinerary:structured_request` | `StructuredLLMResponse` | `query_router` | `inventory_flight_service` |
| `lifetravel_agent` | `itinerary:provider_flight_response` | `ItineraryFlightResponse` | `inventory_flight_service` | `inventory_hotel_service` |
| `lifetravel_agent` | `itinerary:provider_response` | `ItineraryInventoryResponse` | `inventory_hotel_service` | `ranking_service` |
| `lifetravel_agent` | `itinerary:ranked` | `RankedItineraryResponse` | `ranking_service` | `endpoint_api` |
| `lifetravel_agent` | `itinerary:missing_info` | `MissingInfoMessage` (`structured_request.type = "missing_info"`) | `query_router` | `endpoint_api` |
| `lifetravel_agent` | `debug:message` | `DebugMessage` | `inventory_flight_service`, `inventory_hotel_service`, `query_router`, `ranking_service` | `endpoint_api` |
