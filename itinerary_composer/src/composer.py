import copy
import logging
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

import aiohttp

logger = logging.getLogger("itinerary_composer.composer")

# Open Exchange Rates: one table per process, all rates vs USD (base USD).
_USD_RATES_CACHE: dict[str, float] | None = None


def _date_part(dt_str: str) -> str:
    """Extract YYYY-MM-DD from a datetime or date string."""
    return dt_str[:10] if len(dt_str) >= 10 else dt_str


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Exchange-rate helpers (Open Exchange Rates, base USD — cross-rates via USD)
# ---------------------------------------------------------------------------

def _mask_app_id_in_url(url: str) -> str:
    """Avoid logging secrets."""
    if "app_id=" not in url:
        return url
    prefix, _, rest = url.partition("app_id=")
    amp = rest.find("&")
    if amp >= 0:
        return f"{prefix}app_id=***&{rest[amp + 1:]}"
    return f"{prefix}app_id=***"


async def _fetch_usd_rates(latest_url: str) -> dict[str, float]:
    """
    Return map currency_code -> units of that currency per 1 USD (Open Exchange Rates).
    Cached once per process. See https://openexchangerates.org/
    """
    global _USD_RATES_CACHE
    if _USD_RATES_CACHE is not None:
        return _USD_RATES_CACHE
    if not latest_url.strip():
        logger.warning(
            "EXCHANGE_RATE_APP_ID not set; itinerary cost summary uses no FX conversion "
            "(amounts left numerically unchanged when currencies differ)."
        )
        _USD_RATES_CACHE = {"USD": 1.0}
        return _USD_RATES_CACHE

    logger.info("Fetching exchange rates (base=USD): %s", _mask_app_id_in_url(latest_url))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                latest_url,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Open Exchange Rates returned HTTP %s",
                        resp.status,
                    )
                    _USD_RATES_CACHE = {"USD": 1.0}
                    return _USD_RATES_CACHE
                data = await resp.json()
    except Exception:
        logger.warning("Failed to fetch Open Exchange Rates", exc_info=True)
        _USD_RATES_CACHE = {"USD": 1.0}
        return _USD_RATES_CACHE

    base = str(data.get("base", "USD")).upper()
    if base != "USD":
        logger.warning(
            "Open Exchange Rates response base is %r (expected USD); cross-rate math may be wrong",
            base,
        )
    raw_rates = data.get("rates")
    if not isinstance(raw_rates, dict):
        logger.warning("Open Exchange Rates response missing rates object")
        _USD_RATES_CACHE = {"USD": 1.0}
        return _USD_RATES_CACHE

    rates: dict[str, float] = {}
    for k, v in raw_rates.items():
        try:
            rates[str(k).upper()] = float(v)
        except (TypeError, ValueError):
            continue
    rates.setdefault("USD", 1.0)
    _USD_RATES_CACHE = rates
    return _USD_RATES_CACHE


def _convert_via_usd(
    amount: float,
    from_curr: str,
    to_curr: str,
    usd_rates: dict[str, float],
) -> float:
    """
    Convert amount using Open Exchange Rates convention: rate[X] = X per 1 USD.
    Cross-rate: amount_to = amount_from * (rate_to / rate_from).
    """
    from_curr = from_curr.upper()
    to_curr = to_curr.upper()
    if from_curr == to_curr:
        return amount
    rate_from = usd_rates.get(from_curr)
    rate_to = usd_rates.get(to_curr)
    if rate_from is None or rate_from == 0.0 or rate_to is None:
        return amount
    return amount * (rate_to / rate_from)


# ---------------------------------------------------------------------------
# Min-price helpers (currency-aware)
# ---------------------------------------------------------------------------

def _min_flight_price(
    options: list[dict[str, Any]],
    target_currency: str,
    usd_rates: dict[str, float],
) -> float:
    best = float("inf")
    target = target_currency.upper()
    for opt in options:
        price = opt.get("price")
        if not isinstance(price, dict):
            continue
        val = _safe_float(price.get("grandTotal", price.get("total")), float("inf"))
        if val == float("inf"):
            continue
        src = str(price.get("currency", "")).upper()
        if src and src != target:
            val = _convert_via_usd(val, src, target, usd_rates)
        if val < best:
            best = val
    return best if best != float("inf") else 0.0


def _min_hotel_price(
    options: list[dict[str, Any]],
    target_currency: str,
    usd_rates: dict[str, float],
) -> float:
    best = float("inf")
    target = target_currency.upper()
    for opt in options:
        offers = opt.get("offers")
        if not isinstance(offers, list) or not offers:
            continue
        first = offers[0] if isinstance(offers[0], dict) else {}
        price = first.get("price")
        if not isinstance(price, dict):
            continue
        val = _safe_float(price.get("total"), float("inf"))
        if val == float("inf"):
            continue
        src = str(price.get("currency", "")).upper()
        if src and src != target:
            val = _convert_via_usd(val, src, target, usd_rates)
        if val < best:
            best = val
    return best if best != float("inf") else 0.0


# ---------------------------------------------------------------------------
# Budget currency extraction & summary
# ---------------------------------------------------------------------------

def _extract_currencies(payload: dict[str, Any]) -> tuple[str, str]:
    sr = payload.get("structured_request")
    if not isinstance(sr, dict):
        return "USD", "USD"
    output = sr.get("output", sr)
    if not isinstance(output, dict):
        return "USD", "USD"
    budgets = output.get("budgets")
    if not isinstance(budgets, dict):
        return "USD", "USD"
    fb = budgets.get("flights") if isinstance(budgets.get("flights"), dict) else {}
    hb = budgets.get("hotels") if isinstance(budgets.get("hotels"), dict) else {}
    fc = str(fb.get("currency", "USD")).strip() or "USD"
    hc = str(hb.get("currency", "USD")).strip() or "USD"
    return fc, hc


def _compute_summary(
    itinerary: dict[str, Any],
    flights_currency: str,
    hotels_currency: str,
    usd_rates: dict[str, float],
) -> dict[str, Any]:
    flights = itinerary.get("flights", [])
    hotels = itinerary.get("hotels", [])

    total_days = 0
    if flights:
        try:
            d1 = date.fromisoformat(flights[0].get("depart_date", ""))
            d2 = date.fromisoformat(flights[-1].get("arrive_date", ""))
            total_days = (d2 - d1).days
        except (ValueError, TypeError):
            pass

    total_flights_cost = 0.0
    for fg in flights:
        opts = fg.get("options")
        if isinstance(opts, list):
            total_flights_cost += _min_flight_price(opts, flights_currency, usd_rates)

    total_hotels_cost = 0.0
    for hg in hotels:
        opts = hg.get("options")
        if isinstance(opts, list):
            total_hotels_cost += _min_hotel_price(opts, hotels_currency, usd_rates)

    return {
        "total_duration_days": total_days,
        "total_flights_cost": round(total_flights_cost, 2),
        "flights_currency": flights_currency,
        "total_hotels_cost": round(total_hotels_cost, 2),
        "hotels_currency": hotels_currency,
    }


def _build_indexes(
    flight_groups: list[dict[str, Any]],
    hotel_groups: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[tuple[str, str], list[dict[str, Any]]],
]:
    hotels_by_city_checkin: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for hg in hotel_groups:
        key = (hg.get("city_code", ""), hg.get("check_in", ""))
        hotels_by_city_checkin[key].append(hg)

    flights_by_origin_date: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fg in flight_groups:
        key = (fg.get("from", ""), _date_part(fg.get("depart_date", "")))
        flights_by_origin_date[key].append(fg)

    return hotels_by_city_checkin, flights_by_origin_date


_MAX_ITINERARIES = 500


def _enumerate_chains(
    flight_groups: list[dict[str, Any]],
    hotels_by_city_checkin: dict[tuple[str, str], list[dict[str, Any]]],
    flights_by_origin_date: dict[tuple[str, str], list[dict[str, Any]]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    itineraries: list[dict[str, Any]] = []

    def _dfs(
        chain_flights: list[dict[str, Any]],
        chain_hotels: list[dict[str, Any]],
        used_fg: set[int],
        used_hg: set[int],
    ) -> None:
        if len(itineraries) >= _MAX_ITINERARIES:
            return

        last_fg = chain_flights[-1]
        to_code = last_fg.get("to", "")
        arrive_date = _date_part(last_fg.get("arrive_date", ""))

        if to_code == end_destination:
            # Deep copy so each itinerary is independent (no shared nested dicts) and
            # assign a fresh id at creation time (one UUID per appended itinerary).
            itineraries.append({
                "itinerary_id": str(uuid.uuid4()),
                "flights": copy.deepcopy(chain_flights),
                "hotels": copy.deepcopy(chain_hotels),
            })
            return

        matching_hotels = hotels_by_city_checkin.get((to_code, arrive_date), [])

        for hg in matching_hotels:
            if len(itineraries) >= _MAX_ITINERARIES:
                return
            hg_id = id(hg)
            if hg_id in used_hg:
                continue

            city_code = hg.get("city_code", "")
            check_out = hg.get("check_out", "")
            next_flights = flights_by_origin_date.get((city_code, check_out), [])

            for nfg in next_flights:
                nfg_id = id(nfg)
                if nfg_id in used_fg:
                    continue
                chain_flights.append(nfg)
                chain_hotels.append(hg)
                used_fg.add(nfg_id)
                used_hg.add(hg_id)
                _dfs(chain_flights, chain_hotels, used_fg, used_hg)
                chain_flights.pop()
                chain_hotels.pop()
                used_fg.discard(nfg_id)
                used_hg.discard(hg_id)

    for fg in flight_groups:
        if fg.get("from", "") == start_origin:
            _dfs([fg], [], {id(fg)}, set())

    return itineraries


def _extract_trip_endpoints(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (start_origin, end_destination) from the structured request legs."""
    sr = payload.get("structured_request")
    if not isinstance(sr, dict):
        return "", ""
    output = sr.get("output", sr)
    if not isinstance(output, dict):
        return "", ""
    trip = output.get("trip")
    if not isinstance(trip, dict):
        return "", ""
    legs = trip.get("legs")
    if not isinstance(legs, list) or not legs:
        return "", ""
    first_leg = legs[0] if isinstance(legs[0], dict) else {}
    last_leg = legs[-1] if isinstance(legs[-1], dict) else {}
    return str(first_leg.get("from", "")), str(last_leg.get("to", ""))


async def compose_itinerary(
    payload: dict[str, Any],
    *,
    exchange_rate_latest_url: str,
) -> dict[str, Any]:
    """Build all valid flight -> hotel -> flight -> ... chains from the inventory response."""
    provider_response = payload.get("provider_response")
    if not isinstance(provider_response, dict):
        logger.warning("No provider_response in payload (id=%s)", payload.get("id"))
        return {"itineraries": []}

    flight_groups = [fg for fg in provider_response.get("flights", []) if isinstance(fg, dict)]
    hotel_groups = [hg for hg in provider_response.get("hotels", []) if isinstance(hg, dict)]

    if not flight_groups:
        logger.info("No flight groups to compose (id=%s)", payload.get("id"))
        return {"itineraries": []}

    start_origin, end_destination = _extract_trip_endpoints(payload)
    if not start_origin or not end_destination:
        logger.warning(
            "Cannot determine trip start/end from structured_request (id=%s), "
            "start=%r end=%r",
            payload.get("id"),
            start_origin,
            end_destination,
        )
        return {"itineraries": []}

    hotels_by_city_checkin, flights_by_origin_date = _build_indexes(flight_groups, hotel_groups)
    itineraries = _enumerate_chains(
        flight_groups, hotels_by_city_checkin, flights_by_origin_date,
        start_origin, end_destination,
    )

    flights_currency, hotels_currency = _extract_currencies(payload)
    usd_rates = await _fetch_usd_rates(exchange_rate_latest_url)
    for it in itineraries:
        it["summary"] = _compute_summary(it, flights_currency, hotels_currency, usd_rates)

    logger.info(
        "Composed %d itineraries from %d flight groups and %d hotel groups "
        "(start=%s, end=%s, id=%s)",
        len(itineraries),
        len(flight_groups),
        len(hotel_groups),
        start_origin,
        end_destination,
        payload.get("id"),
    )
    return {"itineraries": itineraries}
