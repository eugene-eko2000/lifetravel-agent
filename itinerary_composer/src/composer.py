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
# Budget currency extraction & summary
# ---------------------------------------------------------------------------

def _extract_prompt_id(payload: dict[str, Any]) -> str:
    """OpenAI Responses `id` from the structuring LLM turn; echoed on each composed itinerary."""
    top = payload.get("prompt_id")
    if isinstance(top, str) and top.strip():
        return top.strip()
    sr = payload.get("structured_request")
    if isinstance(sr, dict):
        pid = sr.get("prompt_id")
        if isinstance(pid, str) and pid.strip():
            return pid.strip()
    return ""


def _extract_itinerary_currency(payload: dict[str, Any]) -> str:
    """
    Single display currency for the trip: budgets.itinerary.currency if set, else
    flights budget currency, else hotels budget currency, else USD.
    """
    sr = payload.get("structured_request")
    if not isinstance(sr, dict):
        return "USD"
    output = sr.get("output", sr)
    if not isinstance(output, dict):
        return "USD"
    budgets = output.get("budgets")
    if not isinstance(budgets, dict):
        return "USD"
    itin_b = budgets.get("itinerary")
    if isinstance(itin_b, dict):
        c = str(itin_b.get("currency", "")).strip()
        if c:
            return c.upper()
    fb = budgets.get("flights") if isinstance(budgets.get("flights"), dict) else {}
    fc = str(fb.get("currency", "")).strip()
    if fc:
        return fc.upper()
    hb = budgets.get("hotels") if isinstance(budgets.get("hotels"), dict) else {}
    hc = str(hb.get("currency", "")).strip()
    if hc:
        return hc.upper()
    return "USD"


# Keys whose values are monetary amounts in the dict's `currency` (when present).
_AMOUNT_FIELD_NAMES = frozenset({
    "grandTotal",
    "total",
    "base",
    "amount",
    "price_per_night",
})


def _is_convertible_amount(val: Any) -> bool:
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str) and val.strip():
        try:
            float(val)
            return True
        except (TypeError, ValueError):
            return False
    return False


def _set_itinerary_currency_field(
    parent: dict[str, Any],
    field: str,
    raw_value: Any,
    source_currency: str,
    itinerary_currency: str,
    usd_rates: dict[str, float],
) -> None:
    if not source_currency:
        return
    parsed = _safe_float(raw_value, float("nan"))
    if parsed != parsed:  # NaN
        return
    converted = _convert_via_usd(
        parsed,
        source_currency,
        itinerary_currency,
        usd_rates,
    )
    out_key = f"{field}_itinerary_currency"
    if isinstance(raw_value, str):
        parent[out_key] = f"{converted:.2f}"
    else:
        parent[out_key] = round(converted, 2)


def _annotate_price_tree(
    obj: Any,
    itinerary_currency: str,
    usd_rates: dict[str, float],
    inherited_currency: str | None,
) -> None:
    """
    In-place: for each monetary field in flight/hotel payloads, add
    <field>_itinerary_currency using Open Exchange Rates cross-via-USD conversion.
    """
    if isinstance(obj, dict):
        curr = inherited_currency
        if isinstance(obj.get("currency"), str) and obj["currency"].strip():
            curr = str(obj["currency"]).strip().upper()

        for key in list(obj.keys()):
            if key.endswith("_itinerary_currency"):
                continue
            val = obj[key]
            if key == "currency":
                continue
            if isinstance(val, (dict, list)):
                _annotate_price_tree(val, itinerary_currency, usd_rates, curr)
                continue
            if (
                curr
                and key in _AMOUNT_FIELD_NAMES
                and _is_convertible_amount(val)
            ):
                _set_itinerary_currency_field(
                    obj,
                    key,
                    val,
                    curr,
                    itinerary_currency,
                    usd_rates,
                )
    elif isinstance(obj, list):
        for item in obj:
            _annotate_price_tree(item, itinerary_currency, usd_rates, inherited_currency)


def _annotate_itinerary_flight_hotel_prices(
    itinerary: dict[str, Any],
    itinerary_currency: str,
    usd_rates: dict[str, float],
) -> None:
    flights = itinerary.get("flights")
    if isinstance(flights, list):
        _annotate_price_tree(flights, itinerary_currency, usd_rates, None)
    hotels = itinerary.get("hotels")
    if isinstance(hotels, list):
        _annotate_price_tree(hotels, itinerary_currency, usd_rates, None)


def _compute_summary(
    itinerary: dict[str, Any],
    itinerary_currency: str,
) -> dict[str, Any]:
    flights = itinerary.get("flights", [])

    itinerary_start_date = ""
    itinerary_end_date = ""
    total_days = 0
    if flights:
        dep0 = flights[0].get("depart_date", "")
        arr_last = flights[-1].get("arrive_date", "")
        if dep0:
            itinerary_start_date = _date_part(str(dep0))
        if arr_last:
            itinerary_end_date = _date_part(str(arr_last))
        if itinerary_start_date and itinerary_end_date:
            try:
                d1 = date.fromisoformat(itinerary_start_date)
                d2 = date.fromisoformat(itinerary_end_date)
                total_days = (d2 - d1).days
            except (ValueError, TypeError):
                total_days = 0

    ic = itinerary_currency.upper()

    return {
        "itinerary_start_date": itinerary_start_date,
        "itinerary_end_date": itinerary_end_date,
        "total_duration_days": total_days,
        "itinerary_currency": ic,
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


def _segment_dep_iata(seg: dict[str, Any]) -> str:
    dep = seg.get("departure")
    if isinstance(dep, dict):
        code = dep.get("iataCode")
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    return ""


def _segment_arr_iata(seg: dict[str, Any]) -> str:
    arr = seg.get("arrival")
    if isinstance(arr, dict):
        code = arr.get("iataCode")
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    return ""


def _segment_dep_at(seg: dict[str, Any]) -> str:
    dep = seg.get("departure")
    if isinstance(dep, dict):
        at = dep.get("at")
        if isinstance(at, str) and at.strip():
            return at.strip()
    return ""


def _segment_arr_at(seg: dict[str, Any]) -> str:
    arr = seg.get("arrival")
    if isinstance(arr, dict):
        at = arr.get("at")
        if isinstance(at, str) and at.strip():
            return at.strip()
    return ""


def _option_itinerary_count(opt: dict[str, Any]) -> int:
    itins = opt.get("itineraries")
    if not isinstance(itins, list):
        return 0
    return len(itins)


def _partition_flight_groups(
    flight_groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split groups into single-itinerary options vs multi-itinerary (e.g. full RT from Amadeus).
    A group may appear in both lists with disjoint option sets.
    """
    simple: list[dict[str, Any]] = []
    multi: list[dict[str, Any]] = []
    for fg in flight_groups:
        opts = [o for o in fg.get("options", []) if isinstance(o, dict)]
        multi_o = [o for o in opts if _option_itinerary_count(o) >= 2]
        single_o = [o for o in opts if _option_itinerary_count(o) < 2]
        if single_o:
            simple.append({**fg, "options": single_o})
        if multi_o:
            multi.append({**fg, "options": multi_o})
    return simple, multi


# IATA airports that belong to the same city / metro for hotel↔flight gap matching.
_METRO_AIRPORT_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"LHR", "LCY", "LGW", "STN", "LTN", "LON", "SEN"}),
    frozenset({"JFK", "LGA", "EWR", "SWF", "NYC"}),
    frozenset({"CDG", "ORY", "BVA", "PAR"}),
    frozenset({"NRT", "HND", "TYO"}),
    frozenset({"SFO", "OAK", "SJC"}),
)


def _hotel_city_matches_gap_airports(
    hotel_city: str,
    arrival_airport: str,
    departure_airport: str,
) -> bool:
    """
    Hotel city_code may be a metro code (e.g. LON) while flight segments use
    different airports (e.g. LCY inbound, LHR outbound). Accept if the hotel
    city matches either gap endpoint airport, or all three sit in the same metro.
    """
    hc = str(hotel_city or "").upper().strip()
    aa = str(arrival_airport or "").upper().strip()
    da = str(departure_airport or "").upper().strip()
    if not hc or not aa or not da:
        return False
    if hc in (aa, da):
        return True
    for group in _METRO_AIRPORT_GROUPS:
        if aa in group and da in group and hc in group:
            return True
    return False


def _offer_matches_trip_endpoints(
    opt: dict[str, Any],
    start_origin: str,
    end_destination: str,
) -> bool:
    """First departure and last arrival IATA match trip start/end (case-insensitive)."""
    so = str(start_origin or "").upper().strip()
    ed = str(end_destination or "").upper().strip()
    itins = opt.get("itineraries")
    if not isinstance(itins, list) or not itins:
        return False
    first_itin = itins[0]
    last_itin = itins[-1]
    if not isinstance(first_itin, dict) or not isinstance(last_itin, dict):
        return False
    segs0 = first_itin.get("segments")
    segs1 = last_itin.get("segments")
    if not isinstance(segs0, list) or not segs0 or not isinstance(segs1, list) or not segs1:
        return False
    dep0 = _segment_dep_iata(segs0[0])
    arr1 = _segment_arr_iata(segs1[-1])
    return dep0 == so and arr1 == ed


def _hotel_fits_between_first_two_itineraries(
    hg: dict[str, Any],
    opt: dict[str, Any],
) -> bool:
    """
    Hotel covers the stay between itinerary 1 and 2: last arrival of itin 1 matches
    check-in (date + city); first departure of itin 2 matches check-out (date + city).
    """
    itins = opt.get("itineraries")
    if not isinstance(itins, list) or len(itins) < 2:
        return False
    it0 = itins[0]
    it1 = itins[1]
    if not isinstance(it0, dict) or not isinstance(it1, dict):
        return False
    segs0 = it0.get("segments")
    segs1 = it1.get("segments")
    if not isinstance(segs0, list) or not segs0 or not isinstance(segs1, list) or not segs1:
        return False
    last0 = segs0[-1]
    first1 = segs1[0]
    arr_ap = _segment_arr_iata(last0)
    dep_ap = _segment_dep_iata(first1)
    arr_dt = _segment_arr_at(last0)
    dep_dt = _segment_dep_at(first1)
    if not arr_dt or not dep_dt:
        return False
    hc = str(hg.get("city_code", "")).upper().strip()
    ci = str(hg.get("check_in", "")).strip()
    co = str(hg.get("check_out", "")).strip()
    if not hc or not ci or not co:
        return False
    if not _hotel_city_matches_gap_airports(hc, arr_ap, dep_ap):
        return False
    return _date_part(arr_dt) == _date_part(ci) and _date_part(dep_dt) == _date_part(co)


def _enumerate_multi_itinerary_flight_only(
    multi_fgs: list[dict[str, Any]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fg in multi_fgs:
        opts = fg.get("options", [])
        if not isinstance(opts, list):
            continue
        fitted = [
            o for o in opts
            if isinstance(o, dict)
            and _option_itinerary_count(o) >= 2
            and _offer_matches_trip_endpoints(o, start_origin, end_destination)
        ]
        if not fitted:
            continue
        row = {**fg, "options": fitted}
        out.append({
            "itinerary_id": str(uuid.uuid4()),
            "flights": [copy.deepcopy(row)],
            "hotels": [],
        })
    return out


def _enumerate_multi_itinerary_with_hotels(
    multi_fgs: list[dict[str, Any]],
    hotel_groups: list[dict[str, Any]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    """One flight group (full multi-itinerary offer) + hotels slotted between itin 1 and 2."""
    out: list[dict[str, Any]] = []
    for fg in multi_fgs:
        opts = fg.get("options", [])
        if not isinstance(opts, list):
            continue
        for hg in hotel_groups:
            if not isinstance(hg, dict):
                continue
            fitted = [
                o for o in opts
                if isinstance(o, dict)
                and _option_itinerary_count(o) >= 2
                and _offer_matches_trip_endpoints(o, start_origin, end_destination)
                and _hotel_fits_between_first_two_itineraries(hg, o)
            ]
            if not fitted:
                continue
            row = {**fg, "options": fitted}
            out.append({
                "itinerary_id": str(uuid.uuid4()),
                "flights": [copy.deepcopy(row)],
                "hotels": [copy.deepcopy(hg)],
            })
    return out


_MAX_ITINERARIES = 500


def _flight_edge_ok(last_fg: dict[str, Any], next_fg: dict[str, Any]) -> bool:
    """
    Valid direct flight connection: A.to == B.from and
    A.arrive_date <= B.depart_date (date-only).
    """
    if str(last_fg.get("to", "")) != str(next_fg.get("from", "")):
        return False
    arr_s = _date_part(last_fg.get("arrive_date", ""))
    dep_s = _date_part(next_fg.get("depart_date", ""))
    if not arr_s or not dep_s:
        return False
    try:
        arr_d = date.fromisoformat(arr_s)
        dep_d = date.fromisoformat(dep_s)
    except (ValueError, TypeError):
        return False
    return arr_d <= dep_d


def _enumerate_flight_only_chains(
    flight_groups: list[dict[str, Any]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    """
    When there is no hotel inventory: connect flights where A.to == B.from and
    A.arrive_date <= B.depart_date (dates only). Hotels list is always empty.
    """
    itineraries: list[dict[str, Any]] = []

    def _dfs(chain_flights: list[dict[str, Any]], used_fg: set[int]) -> None:
        if len(itineraries) >= _MAX_ITINERARIES:
            return

        last_fg = chain_flights[-1]
        to_code = str(last_fg.get("to", ""))
        if to_code == end_destination:
            itineraries.append({
                "itinerary_id": str(uuid.uuid4()),
                "flights": copy.deepcopy(chain_flights),
                "hotels": [],
            })
            return

        for nfg in flight_groups:
            nfg_id = id(nfg)
            if nfg_id in used_fg:
                continue
            if not _flight_edge_ok(last_fg, nfg):
                continue
            chain_flights.append(nfg)
            used_fg.add(nfg_id)
            _dfs(chain_flights, used_fg)
            chain_flights.pop()
            used_fg.discard(nfg_id)

    for fg in flight_groups:
        if str(fg.get("from", "")) == start_origin:
            _dfs([fg], {id(fg)})

    return itineraries


def _enumerate_hybrid_chains(
    flight_groups: list[dict[str, Any]],
    hotels_by_city_checkin: dict[tuple[str, str], list[dict[str, Any]]],
    flights_by_origin_date: dict[tuple[str, str], list[dict[str, Any]]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    """
    When some stops have hotel inventory and some do not:
    - If (arrival city, arrival date) has hotel groups: extend with flight → hotel → flight
      (next flight departs on hotel check-out).
    - If there are no hotels for that stop: extend with the next flight only when
      _flight_edge_ok (same rules as flight-only mode).
    """
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
        to_code = str(last_fg.get("to", ""))
        arrive_date = _date_part(last_fg.get("arrive_date", ""))

        if to_code == end_destination:
            itineraries.append({
                "itinerary_id": str(uuid.uuid4()),
                "flights": copy.deepcopy(chain_flights),
                "hotels": copy.deepcopy(chain_hotels),
            })
            return

        matching_hotels = hotels_by_city_checkin.get((to_code, arrive_date), [])

        if matching_hotels:
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
        else:
            for nfg in flight_groups:
                if len(itineraries) >= _MAX_ITINERARIES:
                    return
                nfg_id = id(nfg)
                if nfg_id in used_fg:
                    continue
                if not _flight_edge_ok(last_fg, nfg):
                    continue
                chain_flights.append(nfg)
                used_fg.add(nfg_id)
                _dfs(chain_flights, chain_hotels, used_fg, used_hg)
                chain_flights.pop()
                used_fg.discard(nfg_id)

    for fg in flight_groups:
        if str(fg.get("from", "")) == start_origin:
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
    """
    Build itineraries from the inventory response: flight-only when there are no hotels;
    otherwise hybrid (hotel stay at stops where (city, arrival date) has inventory, else
    direct flight connections between flights).
    """
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

    simple_fgs, multi_fgs = _partition_flight_groups(flight_groups)

    if not hotel_groups:
        itineraries = (
            _enumerate_flight_only_chains(simple_fgs, start_origin, end_destination)
            + _enumerate_multi_itinerary_flight_only(multi_fgs, start_origin, end_destination)
        )
        mode = "flight_only"
    else:
        hotels_by_city_checkin, flights_by_origin_date = _build_indexes(
            simple_fgs, hotel_groups,
        )
        itineraries = (
            _enumerate_hybrid_chains(
                simple_fgs, hotels_by_city_checkin, flights_by_origin_date,
                start_origin, end_destination,
            )
            + _enumerate_multi_itinerary_with_hotels(
                multi_fgs, hotel_groups, start_origin, end_destination,
            )
        )
        mode = "hybrid"

    itinerary_currency = _extract_itinerary_currency(payload)
    prompt_id = _extract_prompt_id(payload)
    usd_rates = await _fetch_usd_rates(exchange_rate_latest_url)
    for it in itineraries:
        it["summary"] = _compute_summary(it, itinerary_currency)
        it["itinerary_currency"] = itinerary_currency.upper()
        if prompt_id:
            it["prompt_id"] = prompt_id
        _annotate_itinerary_flight_hotel_prices(it, itinerary_currency, usd_rates)

    logger.info(
        "Composed %d itineraries (mode=%s) from %d flight groups and %d hotel groups "
        "(start=%s, end=%s, id=%s)",
        len(itineraries),
        mode,
        len(flight_groups),
        len(hotel_groups),
        start_origin,
        end_destination,
        payload.get("id"),
    )
    return {"itineraries": itineraries}
