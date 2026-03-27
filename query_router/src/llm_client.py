import json
from typing import Any

from openai import AsyncOpenAI

from cfg import Cfg


VALID_STRUCTURED_REQUEST_SCHEMA = {
  "type": "object",
  "required": ["trip", "budgets", "confidence"],
  "properties": {
    "trip": {
      "type": "object",
      "required": ["timezone", "legs"],
      "properties": {
        "timezone": {"type": "string"},
        "travelers": {"type": "integer"},
        "legs": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["from", "to", "depart_dates"],
            "properties": {
              "from": {"type": "string"},
              "to": {"type": "string"},
              "depart_dates": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Candidate departure dates (YYYY-MM-DD) for this leg; inventory searches each."
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
              "city": {"type": "string"},
              "city_code": {"type": "string"},
              "location_latlng": {
                "type": "object",
                "required": ["lat", "lng"],
                "properties": {
                  "lat": {"type": "number"},
                  "lng": {"type": "number"}
                }
              },
              "duration": {"type": "integer", "minimum": 1},
              "min_rooms": {"type": "integer"}
            }
          }
        },
        "airline_preferences": {
          "type": "array",
          "items": {"type": "string", "minLength": 2, "maxLength": 3},
          "description": "Optional IATA airline codes (e.g. LH, LX); flight inventory restricts Amadeus offers to these carriers when non-empty."
        }
      }
    },
    "budgets": {
      "type": "object",
      "properties": {
        "flights": {
          "type": "object",
          "properties": {
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "scope": {"enum": ["total_trip", "per_leg"]}
          }
        },
        "hotels": {
          "type": "object",
          "properties": {
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "scope": {"enum": ["per_night", "total_trip"]}
          }
        }
      }
    },
    "assumptions": {
      "type": "array",
      "items": {"type": "string"}
    },
    "missing_fields": {
      "type": "array",
      "items": {"type": "string"}
    },
    "confidence": {"type": "number"}
  }
}


MISSING_INFO_SCHEMA = {
  "type": "object",
  "required": ["missing_info"],
  "properties": {
    "missing_info": {"type": "string"}
  }
}


SYSTEM_PROMPT = f"""You are a helpful assistant that converts 
a user query about a travel itinerary into a structured output.

The user query is expected to contain flight hauls and hotel stays
with dates ranges for each haul and stay and other conditions like 
flight class, hotel rating, etc.

The structured output should be a JSON object that matches the following schema:
{VALID_STRUCTURED_REQUEST_SCHEMA}.

For flights, the from and to fields should be the IATA code of the city metropolitan area.
Each leg must include depart_dates: an array of one or more candidate departure dates (YYYY-MM-DD);
inventory will search flights for each date and merge options.
For hotels, the city_code field should be the IATA code of the city metropolitan area.

If the user prefers specific airlines, set trip.airline_preferences to an array of IATA airline codes
(two letters, e.g. LH, BA, QR). Omit airline_preferences or use an empty array when not specified.

The user can specify beginning and end dates range in a free form. In this case consider multiple departure
dates within a given range.
Example: from 01.05.2026 to 03.05.2026 means 3 beginning dates: 01.05.2026, 02.05.2026, 03.05.2026.
Or if the user says "01.05.2026 with possible range three days" means 6 beginning dates: 28.04.2026,
29.04.2026, 30.04.2026, 01.05.2026, 02.05.2026, 03.05.2026, 04.05.2026. Consider all possible free forms
of specifying a relaxed range of beginning and end dates, like "from 01.05.2026 to 03.05.2026" or
"from 01.05.2026 to 03.05.2026".

The flight legs requests should consider different arrival dates variants for each leg.
Each following leg should have multiple departure dates options. The 1st leg is to have
one departure date equal to the trip start date. the second one should have two departure dates,
the third one three departure dates, etc.

Example:
First flight leg has departure date 2026-05-01.
The next flight leg should consider 2 departure dates: 2026-05-05 and 2026-05-06.
Hotel stays after the 2nd leg should consider check-in dates: 2026-05-06, 2026-05-07, 2026-05-08.

When computing flight and stay dates, please consider the arrival date = departure date.
For hotels, do not include check-in/check-out fields inside stays.
Hotel dates are derived downstream from adjacent flight legs:
check-in = arrival date of leg N, check-out = departure date of leg N+1.
For each stay, include duration as the number of nights/days in that location.
Choose flight departure dates so the time between adjacent flight legs matches each stay duration.

If the user specifies explicitly that hotels aren't needed, stays array should remain empty.

If the user specifies a certain location, not only a city, please find a lat / lng
for this location and put it into the location_latlng field. Leave the location_latlng empty
if the user specifies only the city name or code.

If the user query misses an info for filling in required fields,
the output should contain a text reply that asks the user to provide the missing information.
Example: missing dates for the flight haul, missing cities / locations for the hotel stays.
In that case the missing info output should be a JSON object that matches the following schema:
{MISSING_INFO_SCHEMA}.
"""


def _extract_output_text(response_json: dict[str, Any]) -> str:
    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output_items = response_json.get("output")
    if isinstance(output_items, list):
        for item in output_items:
            if not isinstance(item, dict):
                continue
            content_items = item.get("content")
            if not isinstance(content_items, list):
                continue
            for content_item in content_items:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    return text

    raise ValueError("No text content found in OpenAI response")


async def request_structured_itinerary(
    request_id: str,
    prompt_id: str,
    content: str,
) -> dict[str, Any]:
    """
    Sends a request to OpenAI Responses API and returns:
    {
      "request_id": "...",
      "prompt_id": "...",
      "type": "missing_info" | "valid_request",
      "output": {...}
    }
    """
    cfg = Cfg.from_env()
    if not cfg.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    client = AsyncOpenAI(api_key=cfg.openai_api_key, base_url=cfg.openai_base_url)
    response = await client.responses.create(
        previous_response_id=prompt_id,
        model=cfg.openai_model,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": content}],
            },
        ],
        # Ask the model for structured JSON output.
        text={"format": {"type": "json_object"}},
    )

    response_json: dict[str, Any] = response.model_dump()
    prompt_id = str(response_json.get("id", ""))
    raw_output_text = _extract_output_text(response_json)

    structured_request: Any = json.loads(raw_output_text)

    return {
        "request_id": request_id,
        "prompt_id": prompt_id,
        "type": "missing_info" if structured_request.get("missing_info") is not None else "valid_request",
        "output": structured_request,
    }
