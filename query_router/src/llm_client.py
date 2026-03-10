import json
from typing import Any

from openai import AsyncOpenAI

from cfg import Cfg


VALID_REQUEST_OUTPUT_SCHEMA = {
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
            "required": ["from", "to", "depart_date"],
            "properties": {
              "from": {"type": "string"},
              "to": {"type": "string"},
              "depart_date": {"type": "string", "format": "date"},
              "depart_time_window": {
                "type": "object",
                "properties": {
                  "earliest": {"type": "string", "format": "time"},
                  "latest": {"type": "string", "format": "time"}
                }
              },
              "arrive_date": {"type": "string", "format": "date"},
              "arrive_time_window": {
                "type": "object",
                "properties": {
                  "earliest": {"type": "string", "format": "time"},
                  "latest": {"type": "string", "format": "time"}
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
              "check_in": {"type": "string", "format": "date"},
              "check_out": {"type": "string", "format": "date"},
              "min_rooms": {"type": "integer"}
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


MISSING_INFO_OUTPUT_SCHEMA = {
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
{VALID_REQUEST_OUTPUT_SCHEMA}.

For flights, the from and to fields should be the IATA code of the airport.
For hotels, the city_code field should be the IATA code of the city metropolitan area.

When computing flight and stay dates, please consider the arrival date = departure date + 1 day.
For hotels, please use check-in date as a flight arrival date, next flight departure date as a
hotel check-out date. Calculate the hotel check-out date as a hotel check-in date plus
a number of stayed day unless exact check-in and check-out dates are specified in the user prompt. 

If the user specifies a certain location, not only a city, please find a lat / lng
for this location and put it into the location_latlng field. Leave the location_latlng empty
if the user specifies only the city name or code.

If the user query misses an info for filling in required fields,
the output should contain a text reply that asks the user to provide the missing information.
Example: missing dates for the flight haul, missing cities / locations for the hotel stays.
In that case the missing info output should be a JSON object that matches the following schema:
{MISSING_INFO_OUTPUT_SCHEMA}.
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
