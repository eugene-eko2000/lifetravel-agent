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
`trip.stays` no longer carries `check_in` / `check_out`; hotel stay dates are derived
from adjacent flight legs (`arrival` of leg N to `departure` of leg N+1) in
`inventory_hotel_service`.
Each stay includes `duration` (number of stay days), and flight departure dates are
chosen to align with those durations between adjacent legs.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "StructuredRequest",
  "type": "object",
  "required": ["request_id", "prompt_id", "type", "output"],
  "properties": {
    "request_id": { "type": "string" },
    "prompt_id": { "type": "string" },
    "type": {
      "type": "string",
      "const": "valid_request"
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
            "airline_preferences": {
              "type": "array",
              "items": { "type": "string" },
              "description": "Optional IATA airline codes; flight inventory passes them to Amadeus as included carriers when non-empty."
            },
            "legs": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["from", "to", "depart_dates"],
                "properties": {
                  "from": { "type": "string" },
                  "to": { "type": "string" },
                  "depart_dates": {
                    "type": "array",
                    "items": { "type": "string" },
                    "minItems": 1,
                    "description": "Candidate departure dates per leg; flight inventory queries each and merges offers."
                  }
                }
              }
            },
            "stays": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["duration"],
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
                  "duration": { "type": "integer", "minimum": 1 },
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

### 3) Flight Provider Response Message

Output produced by `inventory_flight_service.request_processor.process_incoming_message(...)`.
Flights are grouped by `(depart_date, arrive_date, from, to)` — one group per unique combination.
In RabbitMQ transport, this object is wrapped as:
`{ "id": "...", "structured_request": {...}, "provider_flight_response": <ItineraryFlightResponse> }`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ItineraryFlightResponse",
  "type": "object",
  "required": ["flights"],
  "properties": {
    "flights": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["depart_date", "arrive_date", "from", "to", "options"],
        "properties": {
          "depart_date": { "type": "string", "format": "date", "description": "Departure date (YYYY-MM-DD) of the 1st segment." },
          "arrive_date": { "type": "string", "format": "date", "description": "Arrival date (YYYY-MM-DD) of the last segment." },
          "from": { "type": "string", "description": "IATA airport code of origin." },
          "to": { "type": "string", "description": "IATA airport code of destination." },
          "options": {
            "type": "array",
            "description": "Amadeus flight offers for this leg.",
            "items": { "type": "object" }
          }
        }
      }
    }
  },
  "additionalProperties": false
}
```

### 4) Itinerary Flight & Hotel Response Message

Output produced by `inventory_hotel_service.request_processor.process_incoming_message(...)`.
It preserves incoming grouped flights and adds hotel options grouped by stay window.
In RabbitMQ transport, this object is wrapped as:
`{ "id": "...", "structured_request": {...}, "provider_response": <ItineraryInventoryResponse> }`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ItineraryInventoryResponse",
  "type": "object",
  "required": ["flights", "hotels"],
  "properties": {
    "flights": {
      "type": "array",
      "description": "Source input from provider_flight_response.flights.",
      "items": {
        "type": "object",
        "required": ["depart_date", "arrive_date", "from", "to", "options"],
        "properties": {
          "depart_date": { "type": "string", "format": "date", "description": "Departure date (YYYY-MM-DD) of the 1st segment." },
          "arrive_date": { "type": "string", "format": "date", "description": "Arrival date (YYYY-MM-DD) of the last segment." },
          "from": { "type": "string", "description": "IATA airport code of origin." },
          "to": { "type": "string", "description": "IATA airport code of destination." },
          "options": { "type": "array", "items": { "type": "object" } }
        }
      }
    },
    "hotels": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["city_code", "check_in", "check_out", "options"],
        "properties": {
          "city_code": { "type": "string", "description": "IATA city/metropolitan area code." },
          "check_in": { "type": "string", "format": "date" },
          "check_out": { "type": "string", "format": "date" },
          "options": {
            "type": "array",
            "description": "Hotel offers for this city/check-in/check-out combination.",
            "items": { "type": "object" }
          }
        }
      }
    }
  },
  "additionalProperties": false
}
```

### 5) ComposedItineraryMessage

Published by `itinerary_composer` for **each** composed itinerary individually.
Each message carries a single itinerary (not a list) together with its index and the
total count so the frontend can track progress.

**Composition rules:** If `provider_response.hotels` is **empty**, itineraries use **flights only**: consecutive flights `A` then `B` are allowed when `A.to == B.from` and `A.arrive_date <= B.depart_date` (date-only), from trip start airport to trip end airport. If `hotels` is **non-empty**, composition is **hybrid** per intermediate stop: where there is hotel inventory for **(arrival city, arrival date)**, the chain uses **flight → hotel → flight** (next flight departs on hotel check-out from that city). Where there is **no** hotel for that stop, the chain continues with **flight → flight** using the same date/location edge rule as flight-only. Each itinerary is capped at 500 variants.

In RabbitMQ transport:
`{ "id": "...", "itinerary_index": 0, "itinerary_count": N, "itinerary": <Itinerary> }`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ComposedItineraryMessage",
  "type": "object",
  "required": ["id", "itinerary_index", "itinerary_count", "itinerary"],
  "properties": {
    "id": { "type": "string", "description": "Request correlation id." },
    "itinerary_index": { "type": "integer", "description": "Zero-based index of this itinerary." },
    "itinerary_count": { "type": "integer", "description": "Total number of itineraries for this request." },
    "itinerary": {
      "type": "object",
      "required": ["itinerary_id", "flights", "hotels", "summary"],
      "properties": {
        "itinerary_id": { "type": "string", "format": "uuid", "description": "Unique id for this composed itinerary instance." },
        "flights": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["depart_date", "arrive_date", "from", "to", "options"],
            "properties": {
              "depart_date": { "type": "string", "format": "date" },
              "arrive_date": { "type": "string", "format": "date" },
              "from": { "type": "string" },
              "to": { "type": "string" },
              "options": { "type": "array", "items": { "type": "object" } }
            }
          }
        },
        "hotels": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["city_code", "check_in", "check_out", "options"],
            "properties": {
              "city_code": { "type": "string" },
              "check_in": { "type": "string", "format": "date" },
              "check_out": { "type": "string", "format": "date" },
              "options": { "type": "array", "items": { "type": "object" } }
            }
          }
        },
        "summary": {
          "type": "object",
          "required": ["itinerary_start_date", "itinerary_end_date", "total_duration_days", "itinerary_currency"],
          "description": "Duration summary and trip currency; per-option prices remain on flight/hotel options (with itinerary_currency annotations).",
          "properties": {
            "itinerary_start_date": { "type": "string", "format": "date", "description": "Date of first flight departure (YYYY-MM-DD); empty when there are no flights." },
            "itinerary_end_date": { "type": "string", "format": "date", "description": "Date of last flight arrival (YYYY-MM-DD); empty when there are no flights." },
            "total_duration_days": { "type": "integer", "description": "Calendar days between itinerary_start_date and itinerary_end_date (last minus first)." },
            "itinerary_currency": { "type": "string", "description": "Single trip currency from structured_request budgets (itinerary, then flights, then hotels, else USD)." }
          }
        }
      }
    }
  },
  "additionalProperties": true
}
```

### 6) EmptyItineraryMessage

Published by `itinerary_composer` when composition yields **no** itineraries (instead of publishing `itinerary:composed`). Consumed by `endpoint_api` and forwarded to the websocket as `type: "no_itineraries"`.

Shape mirrors `query_router` LLM objects (`request_id`, `type`) with the user-facing text under `payload` (like `output` for valid requests).

In RabbitMQ transport (routing key `itinerary:empty`):

`{ "id": "...", "request_id": "...", "type": "no_itineraries", "payload": { "message": "No itinerary found for your request, please refine your request." } }`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EmptyItineraryMessage",
  "type": "object",
  "required": ["id", "request_id", "type", "payload"],
  "properties": {
    "id": { "type": "string", "description": "Pipeline correlation id (same as incoming provider message id)." },
    "request_id": { "type": "string", "description": "Echo of structured_request.request_id when present." },
    "type": { "type": "string", "const": "no_itineraries" },
    "payload": {
      "type": "object",
      "required": ["message"],
      "properties": {
        "message": {
          "type": "string",
          "description": "User-facing explanation that no itinerary could be built."
        }
      }
    }
  },
  "additionalProperties": true
}
```

### 7) RankedItineraryResponse

Published by `ranking_service` for **each** itinerary individually.
Flight and hotel options inside the itinerary are scored and sorted by score descending.

In RabbitMQ transport:
`{ "id": "...", "itinerary_index": 0, "itinerary_count": N, "ranked_itinerary": <RankedItinerary> }`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RankedItineraryResponse",
  "type": "object",
  "required": ["id", "itinerary_index", "itinerary_count", "ranked_itinerary"],
  "properties": {
    "id": { "type": "string", "description": "Request correlation id." },
    "itinerary_index": { "type": "integer", "description": "Zero-based index of this itinerary." },
    "itinerary_count": { "type": "integer", "description": "Total number of itineraries for this request." },
    "ranked_itinerary": {
      "type": "object",
      "required": ["itinerary_id", "flights", "hotels", "summary"],
      "description": "Same shape as ComposedItineraryMessage.itinerary but each option has a _ranking annotation.",
      "properties": {
        "itinerary_id": { "type": "string", "format": "uuid", "description": "Passed through from composed itinerary." },
        "flights": { "type": "array", "items": { "type": "object" } },
        "hotels": { "type": "array", "items": { "type": "object" } },
        "summary": {
          "type": "object",
          "description": "Passed through from composed itinerary; see ComposedItineraryMessage.itinerary.summary."
        }
      }
    }
  },
  "additionalProperties": true
}
```

### 8) MissingInfoMessage

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

### 9) DebugMessage

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

### 10) StatusMessage

Message consumed by `endpoint_api` status subscriber and forwarded to the websocket
request owner (correlated by request id). Published by pipeline stages to report
user-facing processing progress.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "StatusMessage",
  "type": "object",
  "required": ["id", "message"],
  "properties": {
    "id": {
      "type": "string",
      "description": "Request correlation id."
    },
    "message": {
      "type": "string",
      "description": "Human-readable status text."
    }
  },
  "additionalProperties": true
}
```

## Message Routing Table

`exchange name` is configurable via `RABBITMQ_EXCHANGE` (default: `lifetravel_agent`) in all services.

**Pipeline order:** (1) `inventory_flight_service` fetches flights → `itinerary:provider_flight_response`; (2) `inventory_hotel_service` fetches hotels → `itinerary:provider_response`; (3) `itinerary_composer` builds itinerary chains: if none are found it publishes `itinerary:empty`; otherwise it publishes each itinerary separately → `itinerary:composed`; (4) `ranking_service` ranks flights/hotels within each itinerary → `itinerary:ranked`.

**Itinerary composer FX:** Set `EXCHANGE_RATE_APP_ID` in `.env` (passed through `docker-compose.yml` to `itinerary_composer`). It uses [Open Exchange Rates](https://openexchangerates.org/) `latest.json` with **base USD**; other currencies are converted via cross-rates (`amount_to = amount_from × (rate_to / rate_from)` where `rate_X` is units of X per 1 USD). If unset, summary totals are not converted when currencies differ.

| exchange name | routing key | message name | publishers services list | subscribers services list |
| --- | --- | --- | --- | --- |
| `lifetravel_agent` | `itinerary:user_request` | `UserRequestMessage` | `endpoint_api` | `query_router` |
| `lifetravel_agent` | `itinerary:structured_request` | `StructuredRequest` | `query_router` | `inventory_flight_service` |
| `lifetravel_agent` | `itinerary:provider_flight_response` | `ItineraryFlightResponse` | `inventory_flight_service` | `inventory_hotel_service` |
| `lifetravel_agent` | `itinerary:provider_response` | `ItineraryInventoryResponse` | `inventory_hotel_service` | `itinerary_composer` |
| `lifetravel_agent` | `itinerary:composed` | `ComposedItineraryMessage` | `itinerary_composer` | `ranking_service` |
| `lifetravel_agent` | `itinerary:empty` | `EmptyItineraryMessage` | `itinerary_composer` | `endpoint_api` |
| `lifetravel_agent` | `itinerary:ranked` | `RankedItineraryResponse` | `ranking_service` | `endpoint_api` |
| `lifetravel_agent` | `itinerary:missing_info` | `MissingInfoMessage` (`structured_request.type = "missing_info"`) | `query_router` | `endpoint_api` |
| `lifetravel_agent` | `status:message` | `StatusMessage` | `query_router`, `inventory_flight_service`, `inventory_hotel_service`, `itinerary_composer`, `ranking_service` | `endpoint_api` |
| `lifetravel_agent` | `debug:message` | `DebugMessage` | `inventory_flight_service`, `inventory_hotel_service`, `query_router`, `itinerary_composer` | `endpoint_api` |
