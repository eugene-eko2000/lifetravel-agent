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
        "flights_number": {
          "type": "integer",
          "minimum": 1,
          "default": 20,
          "description": "Target maximum number of flight options to consider per leg or group; omit for default 20."
        },
        "hotels_number": {
          "type": "integer",
          "minimum": 1,
          "default": 20,
          "description": "Target maximum number of hotel options to consider per stay; omit for default 20."
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
          },
          "airport_city_codes": {
            "type": "object",
            "description": "Airport IATA code → city code mapping for all airports appearing in this group's options (from Amadeus dictionaries.locations). Omitted when empty.",
            "additionalProperties": { "type": "string" }
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
          "options": { "type": "array", "items": { "type": "object" } },
          "airport_city_codes": {
            "type": "object",
            "description": "Airport IATA code → city code mapping (pass-through from flight inventory). Omitted when empty.",
            "additionalProperties": { "type": "string" }
          }
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
`{ "id": "...", "trip_index": 0, "trip_count": N, "trip": <Trip>, "prompt_id": "...", "structured_request": <StructuredRequest> }`
(`prompt_id` optional; duplicate of `trip.prompt_id` when present. `structured_request` is a deep copy of the
query_router envelope so `ranking_service` can read `output.flights_number` / `output.hotels_number` and other
output fields without duplicating them on `trip`.)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ComposedTripMessage",
  "type": "object",
  "required": ["id", "trip_index", "trip_count", "trip"],
  "properties": {
    "id": { "type": "string", "description": "Request correlation id." },
    "structured_request": {
      "type": "object",
      "description": "Echo of the structuring LLM payload from the inventory message; used by ranking for output.flights_number / output.hotels_number caps."
    },
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
              "options": { "type": "array", "items": { "type": "object" } },
              "airport_city_codes": {
                "type": "object",
                "description": "Airport IATA code → city code mapping (pass-through from flight inventory). Omitted when empty.",
                "additionalProperties": { "type": "string" }
              },
              "itinerary_legs": {
                "type": "array",
                "description": "One entry per itinerary in multi-itinerary offers (e.g. round trips). Omitted for single-itinerary groups.",
                "items": {
                  "type": "object",
                  "required": ["depart", "arrive", "from", "to"],
                  "properties": {
                    "depart": { "type": "string", "description": "Departure datetime (ISO) of the first segment of this itinerary." },
                    "arrive": { "type": "string", "description": "Arrival datetime (ISO) of the last segment of this itinerary." },
                    "from": { "type": "string", "description": "IATA departure airport of this itinerary." },
                    "to": { "type": "string", "description": "IATA arrival airport of this itinerary." }
                  }
                }
              }
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
        "flights": {
          "type": "array",
          "description": "Same shape as ComposedTripMessage flights; each flight group may include `airport_city_codes` and `itinerary_legs` (see ComposedTripMessage schema).",
          "items": { "type": "object" }
        },
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

### 11) Amadeus flight payload (fields used by agent + web + mobile)

The inventory and ranking services consume **Amadeus Flight Offers Search** response shapes (`data[]` offers). `trip_composer` reads segment-level endpoints and itineraries; `ranking_service` uses price, duration, stops, layovers, preferences, and fare details; `inventory_flight_service` groups offers and builds `airport_city_codes` from `dictionaries.locations`. The web/mobile trip UI (`tripFlightFormatting`, `TripFlights`, `tripDualPrice`, `tripShared`) formats segments, carriers, bags, and prices.

The schema below is a **subset**: only fields that appear in code paths are listed. Optional **LifeTravel extensions** on the same objects are noted in descriptions (`_ranking`, `flight_kind`, `*_trip_currency`, etc.).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://lifetravel.ai/schemas/amadeus-flight-offer-subset.json",
  "title": "AmadeusFlightOfferSubset",
  "description": "Subset of Amadeus Flight Offers Search offer objects and related dictionaries as used across lifetravel-agent, lifetravel-frontend-web, and lifetravel-mobile.",
  "type": "object",
  "properties": {
    "dictionaries": { "$ref": "#/$defs/FlightDictionaries" },
    "data": {
      "type": "array",
      "items": { "$ref": "#/$defs/FlightOffer" }
    }
  },
  "additionalProperties": true,
  "$defs": {
    "FlightDictionaries": {
      "type": "object",
      "description": "Merged into provider `flight_dictionaries`; `locations` and `carriers` drive airport→city and airline names in UI.",
      "properties": {
        "locations": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "properties": {
              "cityCode": { "type": "string", "description": "City IATA used for airport_city_codes and locations_dictionary." },
              "countryCode": { "type": "string" }
            },
            "additionalProperties": true
          }
        },
        "carriers": {
          "type": "object",
          "additionalProperties": { "type": "string", "description": "IATA code → airline name (UI carrier lookup)." }
        }
      },
      "additionalProperties": true
    },
    "FlightEndpoint": {
      "type": "object",
      "properties": {
        "iataCode": { "type": "string" },
        "at": { "type": "string", "description": "ISO-8601 local/datetime (segment dep/arr)." },
        "terminal": { "type": "string" },
        "cityName": { "type": "string" },
        "city": { "type": "string" }
      },
      "additionalProperties": true
    },
    "FlightSegment": {
      "type": "object",
      "properties": {
        "id": { "type": "string", "description": "Segment id; matched to fareDetailsBySegment.segmentId." },
        "segmentId": { "type": "string" },
        "duration": { "type": "string", "description": "ISO-8601 duration e.g. PT3H25M." },
        "departure": { "$ref": "#/$defs/FlightEndpoint" },
        "arrival": { "$ref": "#/$defs/FlightEndpoint" },
        "carrierCode": { "type": "string" },
        "number": { "type": ["string", "integer"] },
        "operating": {
          "type": "object",
          "properties": { "carrierCode": { "type": "string" }, "carrier": { "type": "string" } },
          "additionalProperties": true
        }
      },
      "additionalProperties": true
    },
    "FlightItinerary": {
      "type": "object",
      "properties": {
        "duration": { "type": "string", "description": "ISO-8601 duration for whole itinerary (ranking/UI)." },
        "segments": { "type": "array", "items": { "$ref": "#/$defs/FlightSegment" } }
      },
      "additionalProperties": true
    },
    "FlightPrice": {
      "type": "object",
      "description": "Amadeus price object; trip_composer adds parallel `*_trip_currency` string/number fields for converted amounts.",
      "properties": {
        "currency": { "type": "string" },
        "grandTotal": { "type": ["string", "number"] },
        "total": { "type": ["string", "number"] },
        "base": { "type": ["string", "number"] },
        "grandTotal_trip_currency": { "type": ["string", "number"], "description": "LifeTravel: converted grandTotal." },
        "total_trip_currency": { "type": ["string", "number"], "description": "LifeTravel: converted total." },
        "base_trip_currency": { "type": ["string", "number"], "description": "LifeTravel: converted base." }
      },
      "additionalProperties": true
    },
    "IncludedBags": {
      "type": "object",
      "properties": {
        "quantity": { "type": ["integer", "number"] },
        "weight": { "type": ["number", "string"] },
        "maximumWeight": { "type": ["number", "string"] },
        "maxWeight": { "type": ["number", "string"] },
        "weightUnit": { "type": "string" },
        "unit": { "type": "string" }
      },
      "additionalProperties": true
    },
    "FareDetailsBySegment": {
      "type": "object",
      "properties": {
        "segmentId": { "type": "string" },
        "cabin": { "type": "string" },
        "includedCheckedBags": { "$ref": "#/$defs/IncludedBags" },
        "checkedBags": { "$ref": "#/$defs/IncludedBags" },
        "includedCabinBags": { "$ref": "#/$defs/IncludedBags" },
        "cabinBags": { "$ref": "#/$defs/IncludedBags" }
      },
      "additionalProperties": true
    },
    "TravelerPricing": {
      "type": "object",
      "properties": {
        "fareDetailsBySegment": { "type": "array", "items": { "$ref": "#/$defs/FareDetailsBySegment" } }
      },
      "additionalProperties": true
    },
    "PricingOptions": {
      "type": "object",
      "properties": {
        "refundableFare": { "type": "boolean" },
        "includedCheckedBagsOnly": { "type": "boolean" }
      },
      "additionalProperties": true
    },
    "FlightOffer": {
      "type": "object",
      "properties": {
        "id": { "type": "string" },
        "itineraries": { "type": "array", "items": { "$ref": "#/$defs/FlightItinerary" } },
        "price": { "$ref": "#/$defs/FlightPrice" },
        "travelerPricings": { "type": "array", "items": { "$ref": "#/$defs/TravelerPricing" } },
        "pricingOptions": { "$ref": "#/$defs/PricingOptions" },
        "flight_kind": { "type": "string", "description": "LifeTravel inventory: e.g. round_trip." },
        "round_trip_pair_id": { "type": "string", "description": "LifeTravel inventory: correlation id for RT grouping." },
        "_ranking": {
          "type": "object",
          "description": "LifeTravel ranking_service: score, stops, price, duration_minutes, eligible, ineligibility_reason, currency.",
          "additionalProperties": true
        }
      },
      "additionalProperties": true
    }
  }
}
```

**Related grouped inventory fields** (not Amadeus-native; built in `inventory_flight_service` / `trip_composer`): flight group objects may include `depart_date`, `arrive_date`, `from`, `to`, `options` (array of `FlightOffer`), `airport_city_codes`, `itinerary_legs` (`depart`, `arrive`, `from`, `to` per itinerary), and round-trip metadata (`return_from`, `return_to`, `return_depart_date`).

### 12) Amadeus hotel payload (fields used by agent + web + mobile)

**Hotel List** (by city or geocode) supplies `data[].hotelId` and `data[].distance.value` for ordering. **Hotel Search / Booking** offers responses supply `data[]` hotel-offer objects with nested `hotel`, `offers[]`, room and policy details. `inventory_hotel_service` filters on `available` and enriches with `_stay`; `ranking_service` uses price, nights, `hotel` geo, `rating`, `amenities`, cancellation policy; web/mobile (`TripHotels`, `tripDualPrice`, `trip_hotels.dart`) mirror the same paths.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://lifetravel.ai/schemas/amadeus-hotel-offer-subset.json",
  "title": "AmadeusHotelPayloadSubset",
  "description": "Hotel List responses use $defs/HotelListResponse; Hotel Offers Search `data[]` items use $defs/HotelOffersDataItem.",
  "type": "object",
  "additionalProperties": true,
  "$defs": {
    "HotelListResponse": {
      "type": "object",
      "properties": {
        "data": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "hotelId": { "type": "string" },
              "distance": {
                "type": "object",
                "properties": { "value": { "type": "number" } },
                "additionalProperties": true
              }
            },
            "additionalProperties": true
          }
        }
      },
      "additionalProperties": true
    },
    "HotelGeo": {
      "type": "object",
      "properties": {
        "hotelId": { "type": "string" },
        "name": { "type": "string" },
        "chain": { "type": "string" },
        "brand": { "type": "string" },
        "latitude": { "type": "number" },
        "longitude": { "type": "number" },
        "rating": { "type": "number" },
        "amenities": { "type": "array", "items": { "type": "string" } },
        "city_code": { "type": "string" },
        "cityCode": { "type": "string" },
        "city": { "type": "string" },
        "distance": {
          "type": "object",
          "properties": { "value": { "type": "number" } },
          "additionalProperties": true
        },
        "check_in": { "type": "string" },
        "check_out": { "type": "string" },
        "checkIn": { "type": "string" },
        "checkOut": { "type": "string" }
      },
      "additionalProperties": true
    },
    "HotelPrice": {
      "type": "object",
      "properties": {
        "currency": { "type": "string" },
        "grandTotal": { "type": ["string", "number"] },
        "total": { "type": ["string", "number"] },
        "base": { "type": ["string", "number"] },
        "variations": {
          "type": "object",
          "properties": {
            "average": {
              "type": "object",
              "properties": {
                "total": { "type": ["string", "number"] },
                "base": { "type": ["string", "number"] },
                "total_trip_currency": { "description": "LifeTravel: converted." },
                "base_trip_currency": { "description": "LifeTravel: converted." },
                "total_itinerary_currency": { "description": "LifeTravel: synonym used in UI." },
                "base_itinerary_currency": { "description": "LifeTravel: synonym used in UI." }
              },
              "additionalProperties": true
            }
          },
          "additionalProperties": true
        },
        "total_trip_currency": { "type": ["string", "number"], "description": "LifeTravel: converted total." },
        "grandTotal_trip_currency": { "type": ["string", "number"], "description": "LifeTravel: converted grandTotal." }
      },
      "additionalProperties": true
    },
    "RoomTypeEstimated": {
      "type": "object",
      "properties": {
        "category": { "type": "string" },
        "bedType": { "type": "string" },
        "beds": { "type": "number" }
      },
      "additionalProperties": true
    },
    "HotelRoom": {
      "type": "object",
      "properties": {
        "type": { "type": "string" },
        "description": {
          "type": "object",
          "properties": { "text": { "type": "string" } },
          "additionalProperties": true
        },
        "typeEstimated": { "$ref": "#/$defs/RoomTypeEstimated" }
      },
      "additionalProperties": true
    },
    "CancellationPolicy": {
      "type": "object",
      "properties": {
        "type": { "type": "string", "description": "e.g. FULL_STAY, PARTIAL_STAY (ranking)." },
        "deadline": { "type": "string" },
        "numberOfNights": { "type": "number" },
        "policyType": { "type": "string" }
      },
      "additionalProperties": true
    },
    "HotelPolicies": {
      "type": "object",
      "properties": {
        "paymentType": { "type": "string" },
        "refundable": {
          "type": "object",
          "properties": { "cancellationRefund": { "type": "string" } },
          "additionalProperties": true
        },
        "cancellation": { "$ref": "#/$defs/CancellationPolicy" },
        "cancellations": { "type": "array", "items": { "$ref": "#/$defs/CancellationPolicy" } },
        "prepay": {
          "type": "object",
          "properties": {
            "deadline": { "type": "string" },
            "acceptedPayments": {
              "type": "object",
              "properties": {
                "creditCards": { "type": "array", "items": { "type": "string" } },
                "methods": { "type": "array", "items": { "type": "string" } }
              },
              "additionalProperties": true
            }
          },
          "additionalProperties": true
        }
      },
      "additionalProperties": true
    },
    "HotelRateOffer": {
      "type": "object",
      "properties": {
        "checkInDate": { "type": "string" },
        "checkOutDate": { "type": "string" },
        "check_in": { "type": "string" },
        "check_out": { "type": "string" },
        "price": { "$ref": "#/$defs/HotelPrice" },
        "guests": { "type": "object", "properties": { "adults": { "type": "number" } }, "additionalProperties": true },
        "room": { "$ref": "#/$defs/HotelRoom" },
        "roomInformation": {
          "type": "object",
          "properties": {
            "description": { "type": "string" },
            "type": { "type": "string" },
            "typeEstimated": { "$ref": "#/$defs/RoomTypeEstimated" }
          },
          "additionalProperties": true
        },
        "policies": { "$ref": "#/$defs/HotelPolicies" },
        "rateCode": { "type": "string" },
        "rateFamilyEstimated": { "type": "object", "properties": { "code": { "type": "string" } }, "additionalProperties": true },
        "commission": { "type": "object", "properties": { "percentage": { "type": ["number", "string"] } }, "additionalProperties": true }
      },
      "additionalProperties": true
    },
    "HotelOffersDataItem": {
      "type": "object",
      "properties": {
        "available": { "type": "boolean" },
        "error": {},
        "errors": {},
        "hotel": { "$ref": "#/$defs/HotelGeo" },
        "offers": { "type": "array", "items": { "$ref": "#/$defs/HotelRateOffer" } },
        "_stay": {
          "type": "object",
          "description": "LifeTravel inventory_hotel_service: city, city_code, check_in, check_out for the stay context."
        },
        "_ranking": {
          "type": "object",
          "description": "LifeTravel ranking_service: score, price_per_night, eligible, ineligibility_reason, currency; may include price_per_night_trip_currency, total_trip_currency, etc."
        }
      },
      "additionalProperties": true
    }
  }
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
