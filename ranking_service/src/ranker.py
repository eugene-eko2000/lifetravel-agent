from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


EPS = 1e-9

DEFAULT_RANKED_OPTIONS_LIMIT = 20


def _parse_options_limit(raw: Any, *, default: int = DEFAULT_RANKED_OPTIONS_LIMIT) -> int:
    """Structured output uses minimum 1; invalid or missing values fall back to default."""
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw if raw >= 1 else default
    if isinstance(raw, float) and math.isfinite(raw):
        i = int(raw)
        return i if i >= 1 else default
    return default


def _structured_output_options_limits(
    structured_request: dict[str, Any] | None,
) -> tuple[int, int]:
    """
    Read output.flights_number and output.hotels_number from the structured request
    (query_router LLM envelope). Defaults to DEFAULT_RANKED_OPTIONS_LIMIT when absent.
    """
    d = DEFAULT_RANKED_OPTIONS_LIMIT
    if not isinstance(structured_request, dict):
        return d, d
    output = structured_request.get("output", structured_request)
    if not isinstance(output, dict):
        return d, d
    flights_l = (
        _parse_options_limit(output.get("flights_number"))
        if "flights_number" in output
        else d
    )
    hotels_l = (
        _parse_options_limit(output.get("hotels_number"))
        if "hotels_number" in output
        else d
    )
    return flights_l, hotels_l


def _truncate_flight_group_options(
    groups: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        return groups
    out: list[dict[str, Any]] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        ng = dict(g)
        opts = ng.get("options")
        if isinstance(opts, list):
            ng["options"] = opts[:limit]
        out.append(ng)
    return out


def _truncate_flat_flight_offers(
    offers: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        return offers
    return offers[:limit]


def _truncate_hotel_stay_options(
    stays: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        return stays
    out: list[dict[str, Any]] = []
    for s in stays:
        if not isinstance(s, dict):
            continue
        ns = dict(s)
        opts = ns.get("options")
        if isinstance(opts, list):
            ns["options"] = opts[:limit]
        out.append(ns)
    return out


def _truncate_hotels_by_date(
    hotels_map: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    if limit < 1:
        return hotels_map
    out: dict[str, Any] = {}
    for k, v in hotels_map.items():
        if isinstance(v, list):
            out[str(k)] = v[:limit]
        else:
            out[str(k)] = v
    return out


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    # min(hi, nan) is nan in IEEE math, but Python's min(100.0, nan) returns 100.0 — never clamp NaNs via min/max.
    if not math.isfinite(value):
        return lo
    return max(lo, min(hi, value))


def _finite_minmax_values(values: list[float]) -> list[float]:
    """
    Replace non-finite entries so min/max are well-defined.
    +inf maps past the max finite value (worse for lower-is-better after _normalize).
    """
    finite = [v for v in values if math.isfinite(v)]
    if not finite:
        return [0.0] * len(values)
    lo, hi = min(finite), max(finite)
    span = max(hi - lo, 1e-15)
    out: list[float] = []
    for v in values:
        if math.isfinite(v):
            out.append(v)
        elif v > 0:
            out.append(hi + span * 10.0)
        elif v < 0:
            out.append(lo - span * 10.0)
        else:
            out.append((lo + hi) / 2.0)
    return out


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
    # All non-finite (e.g. every hotel missing distance => +inf): no spread; treat as neutral.
    if not any(math.isfinite(v) for v in values):
        return [1.0] * len(values)
    cleaned = _finite_minmax_values(values)
    min_v = min(cleaned)
    max_v = max(cleaned)
    denom = max_v - min_v + EPS
    out: list[float] = []
    for v in cleaned:
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
    for itin in itineraries:
        if not isinstance(itin, dict):
            continue
        dur = itin.get("duration")
        total += _duration_minutes_from_iso8601(dur)
    return total


def _flight_total_stops(offer: dict[str, Any]) -> int:
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list):
        return 99
    stops = 0
    for itin in itineraries:
        segments = itin.get("segments") if isinstance(itin, dict) else None
        if isinstance(segments, list) and segments:
            stops += max(0, len(segments) - 1)
    return stops


def _numeric_price_from_dict(
    price: dict[str, Any],
    *,
    trip_first: tuple[str, ...],
    legacy: tuple[str, ...],
) -> float:
    """
    Prefer trip-composer converted amounts (*_trip_currency), then legacy fields.
    """
    for key in trip_first:
        if key not in price:
            continue
        v = price.get(key)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        parsed = _safe_float(v, float("nan"))
        if parsed == parsed:
            return parsed
    for key in legacy:
        v = price.get(key)
        if v is None:
            continue
        parsed = _safe_float(v, float("nan"))
        if parsed == parsed:
            return parsed
    return float("inf")


def _flight_price(offer: dict[str, Any]) -> float:
    price = offer.get("price")
    if not isinstance(price, dict):
        return float("inf")
    return _numeric_price_from_dict(
        price,
        trip_first=("grandTotal_trip_currency", "total_trip_currency"),
        legacy=("grandTotal", "total"),
    )


def _first_departure_and_last_arrival(offer: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list) or not itineraries:
        return None, None
    first_dep: datetime | None = None
    last_arr: datetime | None = None
    for itin in itineraries:
        segments = itin.get("segments") if isinstance(itin, dict) else None
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
    for itin in itineraries:
        segments = itin.get("segments") if isinstance(itin, dict) else None
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
    for itin in itineraries:
        segments = itin.get("segments") if isinstance(itin, dict) else None
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


_CABIN_PREF_TO_AMADEUS: dict[str, str] = {
    "economy": "ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}


def _normalize_cabin_preference_set(raw: Any) -> set[str] | None:
    if not isinstance(raw, list) or not raw:
        return None
    out: set[str] = set()
    for x in raw:
        if isinstance(x, str):
            key = x.strip().lower()
            am = _CABIN_PREF_TO_AMADEUS.get(key)
            if am:
                out.add(am)
    return out or None


def _normalize_airline_preference_set(raw: Any) -> set[str] | None:
    if not isinstance(raw, list) or not raw:
        return None
    out: set[str] = set()
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.add(x.strip().upper())
    return out or None


def _desired_checked_bags_from_constraints(constraints: dict[str, Any]) -> int | None:
    bp = constraints.get("baggage_preference")
    if not isinstance(bp, dict):
        return None
    n = bp.get("num_checked_bags")
    if isinstance(n, bool):
        return None
    if isinstance(n, int):
        return max(0, n)
    if isinstance(n, float) and math.isfinite(n):
        return max(0, int(n))
    return None


def _merge_trip_flight_preferences(trip: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Overlay trip-level flight preferences onto ranking constraints (trip or trip.trip)."""
    out = dict(base)
    sources: list[dict[str, Any]] = [trip]
    inner = trip.get("trip")
    if isinstance(inner, dict):
        sources.append(inner)
    pref_keys = (
        "cabin_preferences",
        "airline_preferences",
        "baggage_preference",
    )
    for src in sources:
        for key in pref_keys:
            if key not in out and key in src:
                out[key] = src[key]
    return out


def _fare_details_by_segment_id(offer: dict[str, Any]) -> dict[str, tuple[str | None, int | None]]:
    """
    Map Amadeus segmentId -> (cabin upper, included checked bag quantity or None if unknown).
    """
    out: dict[str, tuple[str | None, int | None]] = {}
    tps = offer.get("travelerPricings")
    if not isinstance(tps, list) or not tps:
        return out
    first = tps[0]
    if not isinstance(first, dict):
        return out
    rows = first.get("fareDetailsBySegment")
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("segmentId")
        if sid is None:
            continue
        sid_s = str(sid).strip()
        if not sid_s:
            continue
        cab_raw = row.get("cabin")
        cabin = str(cab_raw).strip().upper() if isinstance(cab_raw, str) and cab_raw.strip() else None
        bags_raw = row.get("includedCheckedBags")
        qty: int | None = None
        if isinstance(bags_raw, dict):
            q = bags_raw.get("quantity")
            if isinstance(q, int):
                qty = max(0, q)
            elif isinstance(q, float) and math.isfinite(q):
                qty = max(0, int(q))
        out[sid_s] = (cabin, qty)
    return out


def _flatten_segment_preference_metrics(
    offer: dict[str, Any],
) -> list[tuple[str, str | None, int | None]]:
    """
    Per segment in itinerary order: (marketing carrier, cabin from fare details or None, bags or None).
    """
    fd_map = _fare_details_by_segment_id(offer)
    itineraries = offer.get("itineraries")
    if not isinstance(itineraries, list):
        return []
    flat_fd = offer.get("travelerPricings")
    fd_list: list[dict[str, Any]] = []
    if isinstance(flat_fd, list) and flat_fd:
        tp0 = flat_fd[0]
        if isinstance(tp0, dict):
            fds = tp0.get("fareDetailsBySegment")
            if isinstance(fds, list):
                fd_list = [x for x in fds if isinstance(x, dict)]

    metrics: list[tuple[str, str | None, int | None]] = []
    fd_idx = 0
    for itin in itineraries:
        if not isinstance(itin, dict):
            continue
        segments = itin.get("segments")
        if not isinstance(segments, list):
            continue
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            cc = str(seg.get("carrierCode", "UNK")).strip().upper() or "UNK"
            sid = seg.get("id")
            sid_s = str(sid).strip() if sid is not None else ""
            cabin: str | None = None
            bags: int | None = None
            if sid_s and sid_s in fd_map:
                cabin, bags = fd_map[sid_s]
            elif fd_idx < len(fd_list):
                row = fd_list[fd_idx]
                fd_idx += 1
                cr = row.get("cabin")
                if isinstance(cr, str) and cr.strip():
                    cabin = cr.strip().upper()
                br = row.get("includedCheckedBags")
                if isinstance(br, dict):
                    q = br.get("quantity")
                    if isinstance(q, int):
                        bags = max(0, q)
                    elif isinstance(q, float) and math.isfinite(q):
                        bags = max(0, int(q))
            metrics.append((cc, cabin, bags))
    return metrics


def _preference_score_adjustments(
    offer: dict[str, Any],
    *,
    cabin_prefs: set[str] | None,
    airline_prefs: set[str] | None,
    desired_bags: int | None,
) -> tuple[float, float, float]:
    """
    Returns (cabin_bonus, airline_bonus, baggage_penalty) to add to raw score.
    Baggage_penalty is positive (subtracted from score later).
    """
    segs = _flatten_segment_preference_metrics(offer)
    if not segs:
        return 0.0, 0.0, 0.0

    cabin_bonus = 0.0
    if cabin_prefs:
        matches = 0
        for _cc, cab, _bags in segs:
            if cab is not None and cab in cabin_prefs:
                matches += 1
        cabin_bonus = 5.0 * (matches / len(segs))

    airline_bonus = 0.0
    if airline_prefs:
        matches = 0
        for cc, _cab, _bags in segs:
            if cc in airline_prefs:
                matches += 1
        airline_bonus = 5.0 * (matches / len(segs))

    baggage_penalty = 0.0
    if desired_bags is not None:
        total_diff = 0.0
        for _cc, _cab, bags in segs:
            actual = 0 if bags is None else float(bags)
            total_diff += abs(float(desired_bags) - actual)
        baggage_penalty = min(40.0, 4.0 * total_diff)

    return cabin_bonus, airline_bonus, baggage_penalty


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
    *,
    currency_label: str = "",
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

    cabin_prefs = _normalize_cabin_preference_set(constraints.get("cabin_preferences"))
    airline_prefs = _normalize_airline_preference_set(constraints.get("airline_preferences"))
    desired_bags = _desired_checked_bags_from_constraints(constraints)

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

        cab_b, air_b, bag_p = _preference_score_adjustments(
            rec["offer"],
            cabin_prefs=cabin_prefs,
            airline_prefs=airline_prefs,
            desired_bags=desired_bags,
        )
        score += cab_b + air_b - bag_p

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
        ranking: dict[str, Any] = {
            "score": round(item["score"], 2),
            "stops": item["stops"],
            "price": item["price"],
            "duration_minutes": round(item["duration"], 2),
            "eligible": item["eligible"],
            "ineligibility_reason": item["ineligibility_reason"],
        }
        if currency_label:
            ranking["currency"] = currency_label
        offer["_ranking"] = ranking
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
    return _numeric_price_from_dict(
        price,
        trip_first=("total_trip_currency",),
        legacy=("total",),
    )


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


def _hotel_geo_coords(offer: dict[str, Any]) -> tuple[float, float] | None:
    """Amadeus hotel search often includes latitude/longitude on the hotel object."""
    hotel = offer.get("hotel")
    if not isinstance(hotel, dict):
        return None
    lat = hotel.get("latitude")
    lng = hotel.get("longitude")
    if isinstance(lat, bool) or isinstance(lng, bool):
        return None
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        if math.isfinite(float(lat)) and math.isfinite(float(lng)):
            return (float(lat), float(lng))
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance on Earth (km)."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


def _stay_reference_latlng_for_city(
    structured_request: dict[str, Any] | None,
    city_code: str,
) -> tuple[float, float] | None:
    """
    If structured_request.output.trip.stays has a stay with matching city_code and
    non-empty location_latlng, return (lat, lng). First matching stay wins.
    """
    if not isinstance(structured_request, dict) or not str(city_code).strip():
        return None
    output = structured_request.get("output", structured_request)
    if not isinstance(output, dict):
        return None
    trip = output.get("trip")
    if not isinstance(trip, dict):
        return None
    stays = trip.get("stays")
    if not isinstance(stays, list):
        return None
    want = str(city_code).strip().upper()
    for stay in stays:
        if not isinstance(stay, dict):
            continue
        if str(stay.get("city_code", "")).strip().upper() != want:
            continue
        ll = stay.get("location_latlng")
        if not isinstance(ll, dict):
            return None
        lat = ll.get("lat")
        lng = ll.get("lng")
        if isinstance(lat, bool) or isinstance(lng, bool):
            return None
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            if math.isfinite(float(lat)) and math.isfinite(float(lng)):
                return (float(lat), float(lng))
        return None
    return None


def _ranking_distance_for_hotel(
    offer: dict[str, Any],
    reference_latlng: tuple[float, float] | None,
) -> float:
    """
    Prefer haversine distance (km) from structured stay location_latlng to hotel coords;
    otherwise Amadeus distance.value (typically km from search center).
    """
    if reference_latlng is not None:
        geo = _hotel_geo_coords(offer)
        if geo is not None:
            return _haversine_km(
                reference_latlng[0],
                reference_latlng[1],
                geo[0],
                geo[1],
            )
    return _hotel_distance(offer)


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


def _reference_latlng_from_constraints(constraints: dict[str, Any]) -> tuple[float, float] | None:
    raw = constraints.get("reference_latlng")
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    a, b = raw[0], raw[1]
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isfinite(float(a)) and math.isfinite(float(b)):
            return (float(a), float(b))
    return None


def _rank_hotels_for_date(
    offers: list[dict[str, Any]],
    constraints: dict[str, Any],
    *,
    currency_label: str = "",
) -> list[dict[str, Any]]:
    if not offers:
        return []

    budget = _safe_float(constraints.get("budget_per_night_cap"), 0.0)
    strict_budget = bool(constraints.get("strict_budget", False))
    min_star = _safe_float(constraints.get("min_star_rating"), 0.0)
    must_have = constraints.get("must_have_amenities")
    must_have_list = must_have if isinstance(must_have, list) else []
    ref_latlng = _reference_latlng_from_constraints(constraints)

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
            "distance": _ranking_distance_for_hotel(offer, ref_latlng),
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

    # When trip.stays[].location_latlng was used, distance is semantically important — weight it higher.
    if ref_latlng is not None:
        w_ppn, w_dist, w_rating, w_cancel, w_amen = (0.23, 0.32, 0.20, 0.15, 0.10)
    else:
        w_ppn, w_dist, w_rating, w_cancel, w_amen = (0.35, 0.20, 0.20, 0.15, 0.10)

    scored: list[dict[str, Any]] = []
    for i, rec in enumerate(eligible):
        score = 100.0 * (
            w_ppn * ppn_norm[i]
            + w_dist * dist_norm[i]
            + w_rating * rating_norm[i]
            + w_cancel * cancel_norm[i]
            + w_amen * amen_norm[i]
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
        ranking: dict[str, Any] = {
            "score": round(item["score"], 2),
            "price_per_night": round(item["ppn"], 2),
            "eligible": item["eligible"],
            "ineligibility_reason": item["ineligibility_reason"],
        }
        if currency_label:
            ranking["currency"] = currency_label
        offer["_ranking"] = ranking
        ranked.append(offer)
    ranked.sort(
        key=lambda x: _safe_float((x.get("_ranking") or {}).get("score"), 0.0),
        reverse=True,
    )
    return ranked


def rank_single_trip(
    trip: dict[str, Any],
    *,
    structured_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rank flight and hotel options inside a single trip.

    Option caps (flights_number / hotels_number) are taken from ``structured_request.output``
    when provided (RabbitMQ path from trip composer); otherwise defaults apply.
    """
    if not isinstance(trip, dict):
        return {
            "flights": [],
            "hotels": [],
            "flight_dictionaries": {},
            "locations_dictionary": {},
        }

    flight_constraints = _merge_trip_flight_preferences(trip, {})
    hotel_constraints: dict[str, Any] = {}

    currency_label = ""
    summary = trip.get("summary")
    if isinstance(summary, dict):
        currency_label = str(summary.get("trip_currency", "") or "").strip()
    if not currency_label:
        currency_label = str(trip.get("trip_currency", "") or "").strip()

    flight_groups = [fg for fg in trip.get("flights", []) if isinstance(fg, dict)]
    hotel_groups = [hg for hg in trip.get("hotels", []) if isinstance(hg, dict)]

    ranked_flights = _rank_flight_groups(
        flight_groups, flight_constraints, currency_label=currency_label
    )
    ranked_hotels = _rank_hotel_stays(
        hotel_groups,
        hotel_constraints,
        structured_request=structured_request,
        currency_label=currency_label,
    )

    flights_limit, hotels_limit = _structured_output_options_limits(structured_request)
    ranked_flights = _truncate_flight_group_options(ranked_flights, flights_limit)
    ranked_hotels = _truncate_hotel_stay_options(ranked_hotels, hotels_limit)

    dicts = trip.get("flight_dictionaries")
    if not isinstance(dicts, dict):
        dicts = {}

    locs = trip.get("locations_dictionary")
    if not isinstance(locs, dict):
        locs = {}
    locations_out: dict[str, str] = {}
    for k, v in locs.items():
        if isinstance(k, str) and k.strip() and isinstance(v, str):
            locations_out[k.strip().upper()] = v

    result = {
        "flights": ranked_flights,
        "hotels": ranked_hotels,
        "flight_dictionaries": dicts,
        "locations_dictionary": locations_out,
    }
    if "summary" in trip:
        result["summary"] = trip["summary"]
    if "trip_id" in trip:
        result["trip_id"] = trip["trip_id"]
    if "prompt_id" in trip:
        result["prompt_id"] = trip["prompt_id"]
    return result


def _rank_flight_groups(
    flights_input: list[dict[str, Any]],
    flight_constraints: dict[str, Any],
    *,
    currency_label: str = "",
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
            "options": _rank_flights(
                options, flight_constraints, currency_label=currency_label
            ),
        }
        ranked_groups.append(group)
    return ranked_groups


def _rank_hotel_stays(
    hotels_input: list[dict[str, Any]],
    hotel_constraints: dict[str, Any],
    *,
    structured_request: dict[str, Any] | None = None,
    currency_label: str = "",
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
        hc = dict(hotel_constraints)
        ref = _stay_reference_latlng_for_city(structured_request, city_code)
        if ref is not None:
            hc["reference_latlng"] = ref
        stay: dict[str, Any] = {
            "check_in": check_in,
            "check_out": check_out,
            "options": _rank_hotels_for_date(
                options, hc, currency_label=currency_label
            ),
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
        return {
            "flights": [],
            "hotels": {},
            "flight_dictionaries": {},
            "locations_dictionary": {},
        }

    constraints = provider_response.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    flight_constraints = constraints.get("flights")
    hotel_constraints = constraints.get("hotels")
    if not isinstance(flight_constraints, dict):
        flight_constraints = {}
    if not isinstance(hotel_constraints, dict):
        hotel_constraints = {}

    sr_raw = provider_response.get("structured_request")
    flights_limit, hotels_limit = _structured_output_options_limits(
        sr_raw if isinstance(sr_raw, dict) else None
    )

    flights_raw = provider_response.get("flights")
    hotels_raw = provider_response.get("hotels")
    flights_input = flights_raw if isinstance(flights_raw, list) else []
    has_grouped_flights = any(
        isinstance(item, dict) and isinstance(item.get("options"), list)
        for item in flights_input
    )

    if has_grouped_flights:
        ranked_flights = _rank_flight_groups(flights_input, flight_constraints)
        ranked_flights = _truncate_flight_group_options(ranked_flights, flights_limit)
    else:
        ranked_flights = _rank_flights(flights_input, flight_constraints)
        ranked_flights = _truncate_flat_flight_offers(ranked_flights, flights_limit)

    sr_for_hotels = sr_raw if isinstance(sr_raw, dict) else None

    if isinstance(hotels_raw, list):
        ranked_hotels = _rank_hotel_stays(
            [x for x in hotels_raw if isinstance(x, dict)],
            hotel_constraints,
            structured_request=sr_for_hotels,
        )
        ranked_hotels = _truncate_hotel_stay_options(ranked_hotels, hotels_limit)
    else:
        hotels_input = hotels_raw if isinstance(hotels_raw, dict) else {}
        ranked_hotels = {}
        for date_key, date_offers in hotels_input.items():
            if not isinstance(date_offers, list):
                continue
            offers = [x for x in date_offers if isinstance(x, dict)]
            city_code = ""
            if offers:
                h0 = offers[0].get("hotel") if isinstance(offers[0], dict) else None
                if isinstance(h0, dict):
                    city_code = str(h0.get("cityCode") or h0.get("city_code") or "")
            hc = dict(hotel_constraints)
            ref = _stay_reference_latlng_for_city(sr_for_hotels, city_code)
            if ref is not None:
                hc["reference_latlng"] = ref
            ranked_hotels[str(date_key)] = _rank_hotels_for_date(offers, hc)
        ranked_hotels = _truncate_hotels_by_date(ranked_hotels, hotels_limit)

    result = dict(provider_response)
    dicts = provider_response.get("flight_dictionaries")
    if not isinstance(dicts, dict):
        dicts = {}
    locs_raw = provider_response.get("locations_dictionary")
    if not isinstance(locs_raw, dict):
        locs_raw = {}
    locations_out: dict[str, str] = {}
    for k, v in locs_raw.items():
        if isinstance(k, str) and k.strip() and isinstance(v, str):
            locations_out[k.strip().upper()] = v
    result["flights"] = ranked_flights
    result["flight_dictionaries"] = dicts
    result["locations_dictionary"] = locations_out
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
