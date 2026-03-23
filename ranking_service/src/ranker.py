from __future__ import annotations

from datetime import date, datetime
from typing import Any


EPS = 1e-9


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_time_hhmm(value: Any) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        hour_str, minute_str = value.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return hour * 60 + minute
    except (TypeError, ValueError):
        return None


def _parse_iso_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # Handle trailing Z
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _duration_minutes_from_iso8601(value: Any) -> float:
    if not isinstance(value, str) or not value.startswith("P"):
        return 0.0
    # Very small PT parser for common Amadeus values: PT#H#M, PT#H, PT#M
    time_part = value.split("T", 1)[1] if "T" in value else ""
    hours = 0
    minutes = 0
    if "H" in time_part:
        h_raw, time_part = time_part.split("H", 1)
        hours = int(h_raw or "0")
    if "M" in time_part:
        m_raw = time_part.split("M", 1)[0]
        minutes = int(m_raw or "0")
    return float(hours * 60 + minutes)


def _normalize(values: list[float], higher_better: bool) -> list[float]:
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    denom = max_v - min_v + EPS
    out: list[float] = []
    for v in values:
        if higher_better:
            out.append((v - min_v) / denom)
        else:
            out.append((max_v - v) / denom)
    return out


def _stops_norm(stops: int) -> float:
    if stops <= 0:
        return 1.0
    if stops == 1:
        return 0.6
    return 0.2


def _time_window_norm(minute_of_day: int, start_min: int, end_min: int) -> float:
    if start_min <= minute_of_day <= end_min:
        return 1.0
    delta = min(abs(minute_of_day - start_min), abs(minute_of_day - end_min))
    # Linear down to 0.5 within 2h, then down to 0.1 by 4h
    if delta <= 120:
        return 1.0 - (delta / 120.0) * 0.5
    if delta <= 240:
        return 0.5 - ((delta - 120.0) / 120.0) * 0.4
    return 0.1


def _extract_flight_offers(flight_results: list[Any]) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for item in flight_results:
        if not isinstance(item, dict):
            continue
        options = item.get("options")
        if isinstance(options, list):
            offers.extend([x for x in options if isinstance(x, dict) and x.get("itineraries")])
            continue
        data = item.get("data")
        if isinstance(data, list):
            offers.extend([x for x in data if isinstance(x, dict)])
        elif isinstance(item, dict) and item.get("itineraries"):
            # Already a flattened offer
            offers.append(item)
    return offers


def _flight_total_duration_minutes(offer: dict[str, Any]) -> float:
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list):
        return 0.0
    total = 0.0
    for itinerary in itineraries:
        if not isinstance(itinerary, dict):
            continue
        dur = itinerary.get("duration")
        total += _duration_minutes_from_iso8601(dur)
    return total


def _flight_total_stops(offer: dict[str, Any]) -> int:
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list):
        return 99
    stops = 0
    for itinerary in itineraries:
        segments = itinerary.get("segments") if isinstance(itinerary, dict) else None
        if isinstance(segments, list) and segments:
            stops += max(0, len(segments) - 1)
    return stops


def _flight_price(offer: dict[str, Any]) -> float:
    price = offer.get("price")
    if not isinstance(price, dict):
        return float("inf")
    return _safe_float(price.get("grandTotal", price.get("total")), float("inf"))


def _first_departure_and_last_arrival(offer: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list) or not itineraries:
        return None, None
    first_dep: datetime | None = None
    last_arr: datetime | None = None
    for itinerary in itineraries:
        segments = itinerary.get("segments") if isinstance(itinerary, dict) else None
        if not isinstance(segments, list) or not segments:
            continue
        dep = _parse_iso_dt((segments[0].get("departure") or {}).get("at"))
        arr = _parse_iso_dt((segments[-1].get("arrival") or {}).get("at"))
        if dep is not None and (first_dep is None or dep < first_dep):
            first_dep = dep
        if arr is not None and (last_arr is None or arr > last_arr):
            last_arr = arr
    return first_dep, last_arr


def _flight_leg_departure_arrival(offer: dict[str, Any]) -> list[tuple[datetime | None, datetime | None]]:
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list):
        return []
    leg_ranges: list[tuple[datetime | None, datetime | None]] = []
    for itinerary in itineraries:
        segments = itinerary.get("segments") if isinstance(itinerary, dict) else None
        if not isinstance(segments, list) or not segments:
            leg_ranges.append((None, None))
            continue
        dep = _parse_iso_dt((segments[0].get("departure") or {}).get("at"))
        arr = _parse_iso_dt((segments[-1].get("arrival") or {}).get("at"))
        leg_ranges.append((dep, arr))
    return leg_ranges


def _extract_leg_date_constraints(
    constraints: dict[str, Any],
) -> list[tuple[set[date] | None, date | None]]:
    """Per leg: (allowed departure dates, expected arrival date or None)."""
    raw_legs = constraints.get("legs")
    if not isinstance(raw_legs, list):
        trip = constraints.get("trip")
        if isinstance(trip, dict):
            raw_legs = trip.get("legs")

    out: list[tuple[set[date] | None, date | None]] = []
    if isinstance(raw_legs, list):
        for leg in raw_legs:
            if not isinstance(leg, dict):
                continue
            dep_set: set[date] = set()
            dd = leg.get("depart_dates")
            if isinstance(dd, list):
                for x in dd:
                    d = _parse_iso_date(x)
                    if d is not None:
                        dep_set.add(d)
            else:
                d = _parse_iso_date(leg.get("depart_date"))
                if d is not None:
                    dep_set.add(d)
            allowed = dep_set if dep_set else None
            arr = _parse_iso_date(leg.get("arrive_date"))
            out.append((allowed, arr))
    if out:
        return out

    # Backward-compatible single-leg shape.
    single_deps = constraints.get("depart_dates")
    if isinstance(single_deps, list):
        dep_set: set[date] = set()
        for x in single_deps:
            d = _parse_iso_date(x)
            if d is not None:
                dep_set.add(d)
        if dep_set:
            return [(dep_set, _parse_iso_date(constraints.get("arrive_date")))]
    single_dep = _parse_iso_date(constraints.get("depart_date"))
    single_arr = _parse_iso_date(constraints.get("arrive_date"))
    if single_dep is not None or single_arr is not None:
        deps: set[date] | None = {single_dep} if single_dep is not None else None
        return [(deps, single_arr)]
    return []


def _minimum_layover_minutes(offer: dict[str, Any]) -> float:
    best: float | None = None
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list):
        return 9999.0
    for itinerary in itineraries:
        segments = itinerary.get("segments") if isinstance(itinerary, dict) else None
        if not isinstance(segments, list) or len(segments) < 2:
            continue
        for idx in range(len(segments) - 1):
            arr = _parse_iso_dt((segments[idx].get("arrival") or {}).get("at"))
            dep = _parse_iso_dt((segments[idx + 1].get("departure") or {}).get("at"))
            if arr is None or dep is None:
                continue
            layover = (dep - arr).total_seconds() / 60.0
            if best is None or layover < best:
                best = layover
    return best if best is not None else 9999.0


def _flight_airline_code(offer: dict[str, Any]) -> str:
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list) or not itineraries:
        return "UNK"
    segments = itineraries[0].get("segments") if isinstance(itineraries[0], dict) else None
    if not isinstance(segments, list) or not segments:
        return "UNK"
    return str(segments[0].get("carrierCode", "UNK"))


def _flight_departure_minute(offer: dict[str, Any]) -> int | None:
    first_dep, _ = _first_departure_and_last_arrival(offer)
    if first_dep is None:
        return None
    return first_dep.hour * 60 + first_dep.minute


def _flight_time_band(minute_of_day: int | None) -> str:
    if minute_of_day is None:
        return "unknown"
    hour = minute_of_day // 60
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _flight_flex_norm(offer: dict[str, Any]) -> float:
    # Best effort over partial provider fields.
    pricing = offer.get("pricingOptions")
    if isinstance(pricing, dict):
        if pricing.get("refundableFare") is True:
            return 1.0
        if pricing.get("includedCheckedBagsOnly") is True:
            return 0.6
    # Default mid score when unknown.
    return 0.6


def _rank_flights(
    flight_results: list[Any],
    constraints: dict[str, Any],
) -> list[dict[str, Any]]:
    offers = _extract_flight_offers(flight_results)
    if not offers:
        return []

    budget_cap = _safe_float(constraints.get("budget_cap"), 0.0)
    budget_strict = bool(constraints.get("strict_budget", False))
    max_stops = constraints.get("max_stops")
    max_duration = _safe_float(constraints.get("max_duration_minutes"), 0.0)
    require_refundable = bool(constraints.get("require_refundable", False))
    min_layover = _safe_float(constraints.get("min_layover_minutes"), 45.0)
    # Ignore time-window constraints for eligibility for now.
    dep_start, dep_end = 7 * 60, 19 * 60
    arr_start, arr_end = 8 * 60, 20 * 60
    leg_date_constraints = _extract_leg_date_constraints(constraints)

    eligible: list[dict[str, Any]] = []
    for offer in offers:
        price = _flight_price(offer)
        duration = _flight_total_duration_minutes(offer)
        stops = _flight_total_stops(offer)
        min_conn = _minimum_layover_minutes(offer)
        dep_dt, arr_dt = _first_departure_and_last_arrival(offer)
        dep_min = dep_dt.hour * 60 + dep_dt.minute if dep_dt else None
        arr_min = arr_dt.hour * 60 + arr_dt.minute if arr_dt else None
        flex = _flight_flex_norm(offer)

        reasons: list[str] = []
        if max_stops is not None and stops > int(max_stops):
            reasons.append("max_stops_exceeded")
        if max_duration > 0 and duration > max_duration:
            reasons.append("max_duration_exceeded")
        if min_conn < min_layover:
            reasons.append("connection_too_tight")
        if require_refundable and flex < 0.99:
            reasons.append("not_refundable")
        if leg_date_constraints:
            offer_legs = _flight_leg_departure_arrival(offer)
            if len(offer_legs) != len(leg_date_constraints):
                reasons.append("legs_count_mismatch")
            for idx, ((dep_expected_set, arr_expected), (dep_actual, arr_actual)) in enumerate(
                zip(leg_date_constraints, offer_legs),
                start=1,
            ):
                if dep_expected_set is not None and len(dep_expected_set) > 0:
                    if dep_actual is None or dep_actual.date() not in dep_expected_set:
                        reasons.append(f"departure_date_mismatch_leg_{idx}")
                if arr_expected is not None and (
                    arr_actual is None or arr_actual.date() != arr_expected
                ):
                    reasons.append(f"arrival_date_mismatch_leg_{idx}")

        rec = {
            "offer": offer,
            "price": price,
            "duration": duration,
            "stops": stops,
            "dep_min": dep_min if dep_min is not None else dep_start,
            "arr_min": arr_min if arr_min is not None else arr_start,
            "min_conn": min_conn,
            "flex": flex,
            "airline": _flight_airline_code(offer),
            "eligible": True,
            "ineligibility_reason": "",
        }

        if budget_cap > 0 and price > budget_cap:
            if budget_strict:
                reasons.append("over_budget_strict")
            elif price > budget_cap * 1.15:
                reasons.append("over_budget_over_15_percent")

        rec["eligible"] = len(reasons) == 0
        rec["ineligibility_reason"] = "; ".join(reasons)
        eligible.append(rec)

    if not eligible:
        return []

    prices = [x["price"] for x in eligible]
    durations = [x["duration"] for x in eligible]
    # Lower layover risk is better -> higher min connection is better.
    conn_safety_raw = [x["min_conn"] for x in eligible]

    price_norm = _normalize(prices, higher_better=False)
    duration_norm = _normalize(durations, higher_better=False)
    conn_norm = _normalize(conn_safety_raw, higher_better=True)

    scored: list[dict[str, Any]] = []
    for i, rec in enumerate(eligible):
        schedule_norm = (
            _time_window_norm(rec["dep_min"], dep_start, dep_end)
            + _time_window_norm(rec["arr_min"], arr_start, arr_end)
        ) / 2.0
        stops_norm = _stops_norm(rec["stops"])
        score = 100.0 * (
            0.30 * price_norm[i]
            + 0.25 * duration_norm[i]
            + 0.15 * stops_norm
            + 0.15 * schedule_norm
            + 0.10 * conn_norm[i]
            + 0.05 * rec["flex"]
        )

        # Business rule re-rank adjustments.
        if rec["stops"] == 0:
            score += 3.0
        elif rec["stops"] >= 2:
            score -= 4.0
        if rec["dep_min"] < 360 or rec["arr_min"] < 360:  # red-eye-ish
            score -= 3.0
        if rec["min_conn"] < 75:
            score -= 4.0
        if rec["flex"] >= 0.95:
            score += 2.0

        if budget_cap > 0 and rec["price"] > budget_cap:
            over_budget_penalty = _clamp((rec["price"] - budget_cap) / budget_cap, 0.0, 1.0)
            score -= 20.0 * over_budget_penalty

        rec_scored = {
            "offer": rec["offer"],
            "score": _clamp(score, 0.0, 100.0),
            "airline": rec["airline"],
            "dep_min": rec["dep_min"],
            "price": rec["price"],
            "duration": rec["duration"],
            "stops": rec["stops"],
            "eligible": rec["eligible"],
            "ineligibility_reason": rec["ineligibility_reason"],
        }
        scored.append(rec_scored)

    ranked: list[dict[str, Any]] = []
    for item in scored:
        offer = dict(item["offer"])
        offer["_ranking"] = {
            "score": round(item["score"], 2),
            "stops": item["stops"],
            "price": item["price"],
            "duration_minutes": round(item["duration"], 2),
            "eligible": item["eligible"],
            "ineligibility_reason": item["ineligibility_reason"],
        }
        ranked.append(offer)
    ranked.sort(
        key=lambda x: _safe_float((x.get("_ranking") or {}).get("score"), 0.0),
        reverse=True,
    )
    return ranked


def _hotel_total_price(offer: dict[str, Any]) -> float:
    offers = offer.get("offers")
    if not isinstance(offers, list) or not offers:
        return float("inf")
    first = offers[0] if isinstance(offers[0], dict) else {}
    price = first.get("price") if isinstance(first, dict) else {}
    if not isinstance(price, dict):
        return float("inf")
    return _safe_float(price.get("total"), float("inf"))


def _hotel_nights(offer: dict[str, Any]) -> int:
    offers = offer.get("offers")
    if not isinstance(offers, list) or not offers:
        return 1
    first = offers[0] if isinstance(offers[0], dict) else {}
    check_in = _parse_iso_dt(str(first.get("checkInDate", "")))
    check_out = _parse_iso_dt(str(first.get("checkOutDate", "")))
    if check_in is None or check_out is None:
        return 1
    nights = (check_out.date() - check_in.date()).days
    return max(1, nights)


def _hotel_price_per_night(offer: dict[str, Any]) -> float:
    return _hotel_total_price(offer) / max(1, _hotel_nights(offer))


def _hotel_distance(offer: dict[str, Any]) -> float:
    hotel = offer.get("hotel")
    if not isinstance(hotel, dict):
        return float("inf")
    distance = hotel.get("distance")
    if isinstance(distance, dict):
        return _safe_float(distance.get("value"), float("inf"))
    return float("inf")


def _hotel_rating(offer: dict[str, Any]) -> float:
    hotel = offer.get("hotel")
    if not isinstance(hotel, dict):
        return 0.0
    return _safe_float(hotel.get("rating"), 0.0)


def _hotel_cancellation_norm(offer: dict[str, Any]) -> float:
    offers = offer.get("offers")
    if not isinstance(offers, list) or not offers:
        return 0.5
    first = offers[0] if isinstance(offers[0], dict) else {}
    policies = first.get("policies") if isinstance(first, dict) else {}
    cancellation = policies.get("cancellation") if isinstance(policies, dict) else None
    if isinstance(cancellation, dict):
        if cancellation.get("type") == "FULL_STAY":
            return 0.2
        if cancellation.get("type") == "PARTIAL_STAY":
            return 0.6
        return 1.0
    return 0.6


def _hotel_amenities_match(offer: dict[str, Any], must_have: list[str]) -> float:
    if not must_have:
        return 1.0
    hotel = offer.get("hotel")
    if not isinstance(hotel, dict):
        return 0.0
    amenities = hotel.get("amenities")
    if not isinstance(amenities, list):
        return 0.0
    available = {str(x).strip().lower() for x in amenities}
    required = [x.strip().lower() for x in must_have if isinstance(x, str) and x.strip()]
    if not required:
        return 1.0
    matched = sum(1 for r in required if r in available)
    return matched / max(1, len(required))


def _rank_hotels_for_date(
    offers: list[dict[str, Any]],
    constraints: dict[str, Any],
) -> list[dict[str, Any]]:
    if not offers:
        return []

    budget = _safe_float(constraints.get("budget_per_night_cap"), 0.0)
    strict_budget = bool(constraints.get("strict_budget", False))
    min_star = _safe_float(constraints.get("min_star_rating"), 0.0)
    must_have = constraints.get("must_have_amenities")
    must_have_list = must_have if isinstance(must_have, list) else []

    eligible: list[dict[str, Any]] = []
    for offer in offers:
        ppn = _hotel_price_per_night(offer)
        rating = _hotel_rating(offer)
        amen_match = _hotel_amenities_match(offer, must_have_list)
        reasons: list[str] = []
        if min_star > 0 and rating < min_star:
            reasons.append("below_min_star_rating")
        if must_have_list and amen_match < 1.0:
            reasons.append("missing_required_amenities")

        rec = {
            "offer": offer,
            "ppn": ppn,
            "distance": _hotel_distance(offer),
            "rating": rating,
            "cancel": _hotel_cancellation_norm(offer),
            "amen": amen_match,
            "eligible": True,
            "ineligibility_reason": "",
        }

        if budget > 0 and ppn > budget:
            if strict_budget:
                reasons.append("over_budget_strict")
            elif ppn > budget * 1.15:
                reasons.append("over_budget_over_15_percent")

        rec["eligible"] = len(reasons) == 0
        rec["ineligibility_reason"] = "; ".join(reasons)
        eligible.append(rec)

    if not eligible:
        return []

    ppn_norm = _normalize([x["ppn"] for x in eligible], higher_better=False)
    dist_norm = _normalize([x["distance"] for x in eligible], higher_better=False)
    rating_norm = _normalize([x["rating"] for x in eligible], higher_better=True)
    cancel_norm = _normalize([x["cancel"] for x in eligible], higher_better=True)
    amen_norm = _normalize([x["amen"] for x in eligible], higher_better=True)

    scored: list[dict[str, Any]] = []
    for i, rec in enumerate(eligible):
        score = 100.0 * (
            0.35 * ppn_norm[i]
            + 0.20 * dist_norm[i]
            + 0.20 * rating_norm[i]
            + 0.15 * cancel_norm[i]
            + 0.10 * amen_norm[i]
        )

        if budget > 0 and rec["ppn"] > budget:
            over_budget_penalty = _clamp((rec["ppn"] - budget) / budget, 0.0, 1.0)
            score -= 20.0 * over_budget_penalty

        scored.append(
            {
                "offer": rec["offer"],
                "score": _clamp(score, 0.0, 100.0),
                "ppn": rec["ppn"],
                "hotel_id": str(((rec["offer"].get("hotel") or {}).get("hotelId", ""))),
                "eligible": rec["eligible"],
                "ineligibility_reason": rec["ineligibility_reason"],
            }
        )

    ranked: list[dict[str, Any]] = []
    for item in scored:
        offer = dict(item["offer"])
        offer["_ranking"] = {
            "score": round(item["score"], 2),
            "price_per_night": round(item["ppn"], 2),
            "eligible": item["eligible"],
            "ineligibility_reason": item["ineligibility_reason"],
        }
        ranked.append(offer)
    ranked.sort(
        key=lambda x: _safe_float((x.get("_ranking") or {}).get("score"), 0.0),
        reverse=True,
    )
    return ranked


def rank_single_itinerary(itinerary: dict[str, Any]) -> dict[str, Any]:
    """Rank flight and hotel options inside a single itinerary."""
    if not isinstance(itinerary, dict):
        return {"flights": [], "hotels": []}

    flight_constraints: dict[str, Any] = {}
    hotel_constraints: dict[str, Any] = {}

    flight_groups = [fg for fg in itinerary.get("flights", []) if isinstance(fg, dict)]
    hotel_groups = [hg for hg in itinerary.get("hotels", []) if isinstance(hg, dict)]

    ranked_flights = _rank_flight_groups(flight_groups, flight_constraints)
    ranked_hotels = _rank_hotel_stays(hotel_groups, hotel_constraints)

    result = {
        "flights": ranked_flights,
        "hotels": ranked_hotels,
    }
    if "summary" in itinerary:
        result["summary"] = itinerary["summary"]
    return result


def _rank_flight_groups(
    flights_input: list[dict[str, Any]],
    flight_constraints: dict[str, Any],
) -> list[dict[str, Any]]:
    ranked_groups: list[dict[str, Any]] = []
    for item in flights_input:
        options_raw = item.get("options")
        if not isinstance(options_raw, list):
            continue
        options = [x for x in options_raw if isinstance(x, dict)]
        group: dict[str, Any] = {
            "depart_date": str(item.get("depart_date", "")),
            "arrive_date": str(item.get("arrive_date", "")),
            "from": str(item.get("from", "")),
            "to": str(item.get("to", "")),
            "options": _rank_flights(options, flight_constraints),
        }
        ranked_groups.append(group)
    return ranked_groups


def _rank_hotel_stays(
    hotels_input: list[dict[str, Any]],
    hotel_constraints: dict[str, Any],
) -> list[dict[str, Any]]:
    ranked_stays: list[dict[str, Any]] = []
    for item in hotels_input:
        city_code = str(item.get("city_code", ""))
        check_in = str(item.get("check_in", ""))
        check_out = str(item.get("check_out", ""))
        options_raw = item.get("options")
        if not isinstance(options_raw, list):
            continue
        options = [x for x in options_raw if isinstance(x, dict)]
        stay: dict[str, Any] = {
            "check_in": check_in,
            "check_out": check_out,
            "options": _rank_hotels_for_date(options, hotel_constraints),
        }
        if city_code:
            stay["city_code"] = city_code
        ranked_stays.append(stay)
    return ranked_stays


def rank_provider_response(provider_response: dict[str, Any]) -> dict[str, Any]:
    """
    Legacy ranking entry point for flat provider_response payloads.

    This function is intentionally defensive with payload parsing because provider
    payloads can vary by endpoint and version.
    """
    if not isinstance(provider_response, dict):
        return {"flights": [], "hotels": {}}

    constraints = provider_response.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    flight_constraints = constraints.get("flights")
    hotel_constraints = constraints.get("hotels")
    if not isinstance(flight_constraints, dict):
        flight_constraints = {}
    if not isinstance(hotel_constraints, dict):
        hotel_constraints = {}

    flights_raw = provider_response.get("flights")
    hotels_raw = provider_response.get("hotels")
    flights_input = flights_raw if isinstance(flights_raw, list) else []
    has_grouped_flights = any(
        isinstance(item, dict) and isinstance(item.get("options"), list)
        for item in flights_input
    )

    if has_grouped_flights:
        ranked_flights = _rank_flight_groups(flights_input, flight_constraints)
    else:
        ranked_flights = _rank_flights(flights_input, flight_constraints)

    if isinstance(hotels_raw, list):
        ranked_hotels: Any = _rank_hotel_stays(
            [x for x in hotels_raw if isinstance(x, dict)],
            hotel_constraints,
        )
    else:
        hotels_input = hotels_raw if isinstance(hotels_raw, dict) else {}
        ranked_hotels = {}
        for date_key, date_offers in hotels_input.items():
            if not isinstance(date_offers, list):
                continue
            offers = [x for x in date_offers if isinstance(x, dict)]
            ranked_hotels[str(date_key)] = _rank_hotels_for_date(offers, hotel_constraints)

    result = dict(provider_response)
    result["flights"] = ranked_flights
    result["hotels"] = ranked_hotels
    flight_count_out = (
        sum(
            len(group.get("options", []))
            for group in ranked_flights
            if isinstance(group, dict) and isinstance(group.get("options"), list)
        )
        if has_grouped_flights
        else len(ranked_flights)
    )
    hotel_groups_out = len(ranked_hotels) if isinstance(ranked_hotels, list) else len(ranked_hotels)
    result["ranking_meta"] = {
        "pipeline": ["score", "annotate_only"],
        "flight_count_in": len(_extract_flight_offers(flights_input)),
        "flight_count_out": flight_count_out,
        "hotel_dates_out": hotel_groups_out,
    }
    return result
