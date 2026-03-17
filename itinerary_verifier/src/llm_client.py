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


def _extract_date_part(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw
    return None


def _extract_flight_dates(itinerary: dict[str, Any]) -> list[dict[str, Any]]:
    flights = itinerary.get("flights")
    if not isinstance(flights, list):
        return []
    extracted: list[dict[str, Any]] = []
    for leg in flights:
        if not isinstance(leg, dict):
            continue
        options_raw = leg.get("options")
        options = options_raw if isinstance(options_raw, list) else []
        departures: set[str] = set()
        arrivals: set[str] = set()
        for option in options:
            if not isinstance(option, dict):
                continue
            itineraries = option.get("itineraries")
            if not isinstance(itineraries, list) or not itineraries:
                continue
            first_itinerary = itineraries[0]
            if not isinstance(first_itinerary, dict):
                continue
            segments = first_itinerary.get("segments")
            if not isinstance(segments, list) or not segments:
                continue
            dep = _extract_date_part((segments[0].get("departure") or {}).get("at"))
            arr = _extract_date_part((segments[-1].get("arrival") or {}).get("at"))
            if dep is not None:
                departures.add(dep)
            if arr is not None:
                arrivals.add(arr)
        extracted.append(
            {
                "date": _extract_date_part(leg.get("date")) or str(leg.get("date", "")),
                "departure_dates": sorted(departures),
                "arrival_dates": sorted(arrivals),
            }
        )
    return extracted


def _extract_hotel_dates(itinerary: dict[str, Any]) -> list[dict[str, Any]]:
    hotels = itinerary.get("hotels")
    if not isinstance(hotels, list):
        return []
    extracted: list[dict[str, Any]] = []
    for stay in hotels:
        if not isinstance(stay, dict):
            continue
        option_check_in_dates: set[str] = set()
        option_check_out_dates: set[str] = set()
        options_raw = stay.get("options")
        options = options_raw if isinstance(options_raw, list) else []
        for option in options:
            if not isinstance(option, dict):
                continue
            offers = option.get("offers")
            if not isinstance(offers, list):
                continue
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                in_date = _extract_date_part(offer.get("checkInDate"))
                out_date = _extract_date_part(offer.get("checkOutDate"))
                if in_date is not None:
                    option_check_in_dates.add(in_date)
                if out_date is not None:
                    option_check_out_dates.add(out_date)
        extracted.append(
            {
                "check_in": _extract_date_part(stay.get("check_in")) or str(stay.get("check_in", "")),
                "check_out": _extract_date_part(stay.get("check_out")) or str(stay.get("check_out", "")),
                "option_check_in_dates": sorted(option_check_in_dates),
                "option_check_out_dates": sorted(option_check_out_dates),
            }
        )
    return extracted


def _extract_itinerary_dates(itinerary: dict[str, Any]) -> dict[str, Any]:
    return {
        "flights": _extract_flight_dates(itinerary),
        "hotels": _extract_hotel_dates(itinerary),
    }


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
    itinerary_dates = _extract_itinerary_dates(itinerary)
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
                Itinerary dates: {itinerary_dates}
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
