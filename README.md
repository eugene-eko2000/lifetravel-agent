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

Object returned by `query_router.llm_client.request_structured_trip(...)`
and published as `payload.structured_request`. The same `prompt_id` (OpenAI Responses
`id` for the structuring turn) is also duplicated at `payload.prompt_id` on messages
from `query_router` through inventory services for convenience.
`trip.stays` no longer carries `check_in` / `check_out`; hotel stay dates are derived
from adjacent flight legs (`arrival` of leg N to `departure` of leg N+1) in
`inventory_hotel_service`.
Each stay includes `duration` (number of stay days), and flight departure dates are
chosen to align with those durations between adjacent legs.
When `trip.cabin_preferences` is non-empty, `inventory_flight_service` adds Amadeus Flight Offers Search
`searchCriteria.flightFilters.cabinRestrictions` (alongside airline carrier filters when set).
When `trip.baggage_preference.num_checked_bags` is set, shopping requests include Amadeus
`searchCriteria.pricingOptions` / `additionalInformation` for baggage-aware search (exact bag count is not a native Amadeus search field).

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
            "cabin_preferences": {
              "type": "array",
              "items": {
                "type": "string",
                "enum": ["economy", "business", "first"]
              },
              "description": "Optional cabin preferences; `inventory_flight_service` maps them to Amadeus `cabinRestrictions` (ECONOMY / BUSINESS / FIRST)."
            },
            "baggage_preference": {
              "type": "object",
              "properties": {
                "num_checked_bags": {
                  "type": "integer",
                  "minimum": 0,
                  "description": "Checked bags per traveler; drives Amadeus search criteria for baggage (see inventory_flight_service)."
                }
              },
              "description": "Optional; omit when not specified."
            },
            "legs": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["from", "to", "depart_dates"],
                "properties": {
                  "from": {
                    "type": "string",
                    "description": "IATA city or metropolitan area code for origin (used by inventory)."
                  },
                  "to": {
                    "type": "string",
                    "description": "IATA city or metropolitan area code for destination (used by inventory)."
                  },
                  "from_location": {
                    "type": "string",
                    "description": "Optional human-readable origin label; complements `from`."
                  },
                  "to_location": {
                    "type": "string",
                    "description": "Optional human-readable destination label; complements `to`."
                  },
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
`flight_dictionaries` (when present) is merged from Amadeus flight-offers `data.dictionaries` across
all fetches for the request (e.g. `locations`, `carriers`, `aircraft`) so clients can resolve codes
referenced in offers.
In RabbitMQ transport, this object is wrapped as:
`{ "id": "...", "structured_request": {...}, "prompt_id": "...", "provider_flight_response": <TripFlightResponse> }`
(`prompt_id` optional; echoed from `structured_request.prompt_id` / query_router).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "TripFlightResponse",
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
    },
    "flight_dictionaries": {
      "type": "object",
      "description": "Merged Amadeus flight shopping dictionaries for this request; omitted when empty.",
      "additionalProperties": true
    }
  },
  "additionalProperties": false
}
```

### 4) Trip Flight & Hotel Response Message

Output produced by `inventory_hotel_service.request_processor.process_incoming_message(...)`.
It preserves incoming grouped flights and adds hotel options grouped by stay window.
When the incoming flight message included `provider_flight_response.flight_dictionaries`, the same
object is copied onto `provider_response.flight_dictionaries`.
In RabbitMQ transport, this object is wrapped as:
`{ "id": "...", "structured_request": {...}, "prompt_id": "...", "provider_response": <TripInventoryResponse> }`
(`prompt_id` optional).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "TripInventoryResponse",
  "type": "object",
  "required": ["flights", "hotels"],
  "properties": {
    "flight_dictionaries": {
      "type": "object",
      "description": "Pass-through from `provider_flight_response.flight_dictionaries` when present; merged Amadeus dictionaries for decoding flight offers.",
      "additionalProperties": true
    },
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

### 5) ComposedTripMessage

Published by `trip_composer` for **each** composed trip individually.
Each message carries a single trip (not a list) together with its index and the
total count so the frontend can track progress.

**Composition rules:** If `provider_response.hotels` is **empty**, trips use **flights only**: consecutive flights `A` then `B` are allowed when `A.to == B.from` and `A.arrive_date <= B.depart_date` (date-only), from trip start airport to trip end airport. If `hotels` is **non-empty**, composition is **hybrid** per intermediate stop: where there is hotel inventory for **(arrival city, arrival date)**, the chain uses **flight → hotel → flight** (next flight departs on hotel check-out from that city). Where there is **no** hotel for that stop, the chain continues with **flight → flight** using the same date/location edge rule as flight-only. Each trip is capped at 500 variants.
`provider_response.flight_dictionaries` (when present) is copied onto each composed `trip.flight_dictionaries`.
`trip.locations_dictionary` maps IATA codes to human-readable labels from the structured request:
each leg contributes `from` → `from_location` and `to` → `to_location`; each stay contributes
`city_code` → `city` (stays overwrite a code if it was already set from a leg).

In RabbitMQ transport:
`{ "id": "...", "trip_index": 0, "trip_count": N, "trip": <Trip>, "prompt_id": "..." }`
(`prompt_id` optional; duplicate of `trip.prompt_id` when present).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ComposedTripMessage",
  "type": "object",
  "required": ["id", "trip_index", "trip_count", "trip"],
  "properties": {
    "id": { "type": "string", "description": "Request correlation id." },
    "prompt_id": { "type": "string", "description": "Optional duplicate of trip.prompt_id for envelope consumers." },
    "trip_index": { "type": "integer", "description": "Zero-based index of this trip." },
    "trip_count": { "type": "integer", "description": "Total number of trips for this request." },
    "trip": {
      "type": "object",
      "required": ["trip_id", "flights", "hotels", "summary", "locations_dictionary"],
      "properties": {
        "trip_id": { "type": "string", "format": "uuid", "description": "Unique id for this composed trip instance." },
        "prompt_id": {
          "type": "string",
          "description": "OpenAI Responses id from the LLM structuring turn; use as previous_response_id for follow-up turns. Same nesting as trip correlation fields."
        },
        "flight_dictionaries": {
          "type": "object",
          "description": "Merged Amadeus flight dictionaries for this pipeline request; copied from `provider_response` when present.",
          "additionalProperties": true
        },
        "locations_dictionary": {
          "type": "object",
          "description": "IATA code → display string from structured_request `trip.legs` (from/to locations) and `trip.stays` (city_code → city); empty object when none.",
          "additionalProperties": { "type": "string" }
        },
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
          "required": ["trip_start_date", "trip_end_date", "total_duration_days", "trip_currency"],
          "description": "Duration summary and trip currency; per-option prices remain on flight/hotel options (with trip_currency annotations).",
          "properties": {
            "trip_start_date": { "type": "string", "format": "date", "description": "Date of first flight departure (YYYY-MM-DD); empty when there are no flights." },
            "trip_end_date": { "type": "string", "format": "date", "description": "Date of last flight arrival (YYYY-MM-DD); empty when there are no flights." },
            "total_duration_days": { "type": "integer", "description": "Calendar days between trip_start_date and trip_end_date (last minus first)." },
            "trip_currency": { "type": "string", "description": "Single trip currency from structured_request budgets (trip, then flights, then hotels, else USD)." }
          }
        }
      }
    }
  },
  "additionalProperties": true
}
```

### 6) EmptyTripMessage

Published by `trip_composer` when composition yields **no** trips (instead of publishing `trip:composed`). Consumed by `endpoint_api` and forwarded to the websocket as `type: "no_trips"`.

Shape mirrors `query_router` LLM objects (`request_id`, `type`) with the user-facing text under `payload` (like `output` for valid requests).

In RabbitMQ transport (routing key `trip:empty`):

`{ "id": "...", "request_id": "...", "type": "no_trips", "prompt_id": "...", "payload": { "message": "..." } }`
(`prompt_id` optional when known from `structured_request`.)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EmptyTripMessage",
  "type": "object",
  "required": ["id", "request_id", "type", "payload"],
  "properties": {
    "id": { "type": "string", "description": "Pipeline correlation id (same as incoming provider message id)." },
    "request_id": { "type": "string", "description": "Echo of structured_request.request_id when present." },
    "prompt_id": { "type": "string", "description": "Optional; OpenAI structuring turn id when available." },
    "type": { "type": "string", "const": "no_trips" },
    "payload": {
      "type": "object",
      "required": ["message"],
      "properties": {
        "message": {
          "type": "string",
          "description": "User-facing explanation that no trip could be built."
        }
      }
    }
  },
  "additionalProperties": true
}
```

### 7) RankedTripResponse

Published by `ranking_service` for **each** trip individually.
Flight and hotel options inside the trip are scored and sorted by score descending.
`locations_dictionary` is passed through from the composed trip (keys normalized to uppercase).

In RabbitMQ transport:
`{ "id": "...", "trip_index": 0, "trip_count": N, "ranked_trip": <RankedTrip>, "prompt_id": "..." }`
(`prompt_id` optional; duplicate of `ranked_trip.prompt_id` when present).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RankedTripResponse",
  "type": "object",
  "required": ["id", "trip_index", "trip_count", "ranked_trip"],
  "properties": {
    "id": { "type": "string", "description": "Request correlation id." },
    "prompt_id": { "type": "string", "description": "Optional duplicate of ranked_trip.prompt_id." },
    "trip_index": { "type": "integer", "description": "Zero-based index of this trip." },
    "trip_count": { "type": "integer", "description": "Total number of trips for this request." },
    "ranked_trip": {
      "type": "object",
      "required": ["trip_id", "flights", "hotels", "summary", "flight_dictionaries", "locations_dictionary"],
      "description": "Same shape as ComposedTripMessage.trip but each option has a _ranking annotation; `flight_dictionaries` and `locations_dictionary` are always present (empty object when none).",
      "properties": {
        "trip_id": { "type": "string", "format": "uuid", "description": "Passed through from composed trip." },
        "prompt_id": { "type": "string", "description": "Passed through from composed trip; OpenAI structuring turn id." },
        "flight_dictionaries": {
          "type": "object",
          "description": "Merged Amadeus flight dictionaries; passed through from composed trip (empty object when none).",
          "additionalProperties": true
        },
        "locations_dictionary": {
          "type": "object",
          "description": "IATA code → display string from structured request; keys normalized to uppercase.",
          "additionalProperties": { "type": "string" }
        },
        "flights": { "type": "array", "items": { "type": "object" } },
        "hotels": { "type": "array", "items": { "type": "object" } },
        "summary": {
          "type": "object",
          "description": "Passed through from composed trip; see ComposedTripMessage.trip.summary."
        }
      }
    }
  },
  "additionalProperties": true
}
```

### 8) MissingInfoMessage

Message published by `query_router` when the LLM cannot build a complete trip request
and consumed by `endpoint_api` subscriber/websocket bridge. The websocket payload may
include a top-level `prompt_id` (duplicate of `structured_request.prompt_id`) for clients
that read a flat envelope.

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
    "prompt_id": {
      "type": "string",
      "description": "Optional duplicate of structured_request.prompt_id (OpenAI structuring turn id)."
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

**Pipeline order:** (1) `inventory_flight_service` fetches flights → `trip:provider_flight_response`; (2) `inventory_hotel_service` fetches hotels → `trip:provider_response`; (3) `trip_composer` builds trip chains: if none are found it publishes `trip:empty`; otherwise it publishes each trip separately → `trip:composed`; (4) `ranking_service` ranks flights/hotels within each trip → `trip:ranked`.

**Trip composer FX:** Set `EXCHANGE_RATE_APP_ID` in `.env` (passed through `docker-compose.yml` to `trip_composer`). It uses [Open Exchange Rates](https://openexchangerates.org/) `latest.json` with **base USD**; other currencies are converted via cross-rates (`amount_to = amount_from × (rate_to / rate_from)` where `rate_X` is units of X per 1 USD). If unset, summary totals are not converted when currencies differ.

| exchange name | routing key | message name | publishers services list | subscribers services list |
| --- | --- | --- | --- | --- |
| `lifetravel_agent` | `trip:user_request` | `UserRequestMessage` | `endpoint_api` | `query_router` |
| `lifetravel_agent` | `trip:structured_request` | `StructuredRequest` | `query_router` | `inventory_flight_service` |
| `lifetravel_agent` | `trip:provider_flight_response` | `TripFlightResponse` | `inventory_flight_service` | `inventory_hotel_service` |
| `lifetravel_agent` | `trip:provider_response` | `TripInventoryResponse` | `inventory_hotel_service` | `trip_composer` |
| `lifetravel_agent` | `trip:composed` | `ComposedTripMessage` | `trip_composer` | `ranking_service` |
| `lifetravel_agent` | `trip:empty` | `EmptyTripMessage` | `trip_composer` | `endpoint_api` |
| `lifetravel_agent` | `trip:ranked` | `RankedTripResponse` | `ranking_service` | `endpoint_api` |
| `lifetravel_agent` | `trip:missing_info` | `MissingInfoMessage` (`structured_request.type = "missing_info"`) | `query_router` | `endpoint_api` |
| `lifetravel_agent` | `status:message` | `StatusMessage` | `query_router`, `inventory_flight_service`, `inventory_hotel_service`, `trip_composer`, `ranking_service` | `endpoint_api` |
| `lifetravel_agent` | `debug:message` | `DebugMessage` | `inventory_flight_service`, `inventory_hotel_service`, `query_router`, `trip_composer` | `endpoint_api` |
