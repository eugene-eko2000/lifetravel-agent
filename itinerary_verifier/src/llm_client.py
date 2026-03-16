import json
from typing import Any

from openai import AsyncOpenAI

from cfg import Cfg


ADJUSTED_STRUCTURED_REQUEST_SCHEMA: dict[str, Any] = {
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
                                    "latest": {"type": "string", "format": "time"},
                                },
                            },
                            "arrive_date": {"type": "string", "format": "date"},
                            "arrive_time_window": {
                                "type": "object",
                                "properties": {
                                    "earliest": {"type": "string", "format": "time"},
                                    "latest": {"type": "string", "format": "time"},
                                },
                            },
                        },
                    },
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
                                    "lng": {"type": "number"},
                                },
                            },
                            "duration": {"type": "integer", "minimum": 1},
                            "min_rooms": {"type": "integer"},
                        },
                    },
                },
            },
        },
        "budgets": {
            "type": "object",
            "properties": {
                "flights": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "currency": {"type": "string"},
                        "scope": {"enum": ["total_trip", "per_leg"]},
                    },
                },
                "hotels": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "currency": {"type": "string"},
                        "scope": {"enum": ["per_night", "total_trip"]},
                    },
                },
            },
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "missing_fields": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {"type": "number"},
    },
}

VERIFIER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["match_ok"],
    "properties": {
        "match_ok": {"type": "boolean"},
        "mismatches": {
            "type": "array",
            "items": {"type": "string"},
        },
        "adjusted_structured_request": ADJUSTED_STRUCTURED_REQUEST_SCHEMA,
    },
    "additionalProperties": True,
}


# Intentionally left empty per current requirement.
SYSTEM_PROMPT = f"""
You are a helpful assistant that verifies the itinerary against the structured request.

You are expected to return either a verification success or a verification
failure with explanation of all mismatchings between the itinerary and the structured request.

You will get the structured request and the itinerary as two JSON objects.
The structured request is the original request from the user, and the itinerary is the verified
itinerary.

You should verify matches between stay durations in the structured request and stay durations
in the itinerary. If there are mismatches, the flight departure dates should be stretched to
fit all stay durations. The initial structured request might be unresolvable because some flights
have duration longer than one day. To make it matching, you should move flight legs forward in
time to make stays durations fit between flights.

The verification output should be a JSON object that matches the following schema:
{VERIFIER_OUTPUT_SCHEMA}.

If the itinerary fully matches the structured request,
the "match_ok" field should be true and all other fields should be omitted.
If there are mismatches, the "match_ok" field should be false and the "mismatches" field should be an array
of strings explaining the mismatches. The "adjusted_structured_request" field should be the adjusted structured request
that contains the structured request matching the itinerary.
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


def _extract_structured_request_and_itinerary(content: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload: Any = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("content must be a JSON string with structured_request/provider_response") from error

    if not isinstance(payload, dict):
        raise ValueError("content must decode to an object payload")

    structured_request = payload.get("structured_request")
    itinerary = payload.get("provider_response")
    if not isinstance(structured_request, dict):
        raise ValueError("content payload must contain object field 'structured_request'")
    if not isinstance(itinerary, dict):
        raise ValueError("content payload must contain object field 'provider_response'")

    return structured_request, itinerary


async def request_structured_output(
    request_id: str,
    prompt_id: str,
    content: str,
) -> dict[str, Any]:
    """
    Sends a request to OpenAI Responses API and returns:
    {
      "request_id": "...",
      "prompt_id": "...",
      "output": {...}
    }
    """
    structured_request, itinerary = _extract_structured_request_and_itinerary(content)
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
                "content": [{"type": "input_text", "text": f"""
                Structured request: {structured_request}
                Itinerary: {itinerary}
                """}],
            },
        ],
        # Ask the model for structured JSON output.
        text={"format": {"type": "json_object"}},
    )

    response_json: dict[str, Any] = response.model_dump()
    next_prompt_id = str(response_json.get("id", ""))
    raw_output_text = _extract_output_text(response_json)

    structured_output: Any = json.loads(raw_output_text)

    return {
        "request_id": request_id,
        "prompt_id": next_prompt_id,
        "output": structured_output,
    }
