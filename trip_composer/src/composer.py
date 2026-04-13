import copy
import itertools
import logging
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

import aiohttp

logger = logging.getLogger("trip_composer.composer")

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
            "EXCHANGE_RATE_APP_ID not set; trip cost summary uses no FX conversion "
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
    """OpenAI Responses `id` from the structuring LLM turn; echoed on each composed trip."""
    top = payload.get("prompt_id")
    if isinstance(top, str) and top.strip():
        return top.strip()
    sr = payload.get("structured_request")
    if isinstance(sr, dict):
        pid = sr.get("prompt_id")
        if isinstance(pid, str) and pid.strip():
            return pid.strip()
    return ""


def _extract_trip_currency(payload: dict[str, Any]) -> str:
    """
    Single display currency for the trip: budgets.trip.currency if set, else
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
    itin_b = budgets.get("trip")
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


def _set_trip_currency_field(
    parent: dict[str, Any],
    field: str,
    raw_value: Any,
    source_currency: str,
    trip_currency: str,
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
        trip_currency,
        usd_rates,
    )
    out_key = f"{field}_trip_currency"
    if isinstance(raw_value, str):
        parent[out_key] = f"{converted:.2f}"
    else:
        parent[out_key] = round(converted, 2)


def _annotate_price_tree(
    obj: Any,
    trip_currency: str,
    usd_rates: dict[str, float],
    inherited_currency: str | None,
) -> None:
    """
    In-place: for each monetary field in flight/hotel payloads, add
    <field>_trip_currency using Open Exchange Rates cross-via-USD conversion.
    """
    if isinstance(obj, dict):
        curr = inherited_currency
        if isinstance(obj.get("currency"), str) and obj["currency"].strip():
            curr = str(obj["currency"]).strip().upper()

        for key in list(obj.keys()):
            if key.endswith("_trip_currency"):
                continue
            val = obj[key]
            if key == "currency":
                continue
            if isinstance(val, (dict, list)):
                _annotate_price_tree(val, trip_currency, usd_rates, curr)
                continue
            if (
                curr
                and key in _AMOUNT_FIELD_NAMES
                and _is_convertible_amount(val)
            ):
                _set_trip_currency_field(
                    obj,
                    key,
                    val,
                    curr,
                    trip_currency,
                    usd_rates,
                )
    elif isinstance(obj, list):
        for item in obj:
            _annotate_price_tree(item, trip_currency, usd_rates, inherited_currency)


def _annotate_trip_flight_hotel_prices(
    trip: dict[str, Any],
    trip_currency: str,
    usd_rates: dict[str, float],
) -> None:
    flights = trip.get("flights")
    if isinstance(flights, list):
        _annotate_price_tree(flights, trip_currency, usd_rates, None)
    hotels = trip.get("hotels")
    if isinstance(hotels, list):
        _annotate_price_tree(hotels, trip_currency, usd_rates, None)


def _compute_summary(
    trip: dict[str, Any],
    trip_currency: str,
) -> dict[str, Any]:
    flights = trip.get("flights", [])

    trip_start_date = ""
    trip_end_date = ""
    total_days = 0
    if flights:
        first_fg = flights[0]
        last_fg = flights[-1]

        first_legs = first_fg.get("itinerary_legs")
        if isinstance(first_legs, list) and first_legs:
            dep0 = first_legs[0].get("depart", "")
        else:
            dep0 = first_fg.get("depart_date", "")

        last_legs = last_fg.get("itinerary_legs")
        if isinstance(last_legs, list) and last_legs:
            arr_last = last_legs[-1].get("arrive", "")
        else:
            arr_last = last_fg.get("arrive_date", "")

        if dep0:
            trip_start_date = _date_part(str(dep0))
        if arr_last:
            trip_end_date = _date_part(str(arr_last))
        if trip_start_date and trip_end_date:
            try:
                d1 = date.fromisoformat(trip_start_date)
                d2 = date.fromisoformat(trip_end_date)
                total_days = (d2 - d1).days
            except (ValueError, TypeError):
                total_days = 0

    return {
        "trip_start_date": trip_start_date,
        "trip_end_date": trip_end_date,
        "total_duration_days": total_days,
        "trip_currency": trip_currency.upper(),
    }


def _build_indexes(
    acc: dict[str, str],
    flight_groups: list[dict[str, Any]],
    hotel_groups: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[tuple[str, str], list[dict[str, Any]]],
]:
    hotels_by_city_checkin: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for hg in hotel_groups:
        city = hg.get("city_code", "")
        ci = hg.get("check_in", "")
        hotels_by_city_checkin[(city, ci)].append(hg)
        resolved = _resolve_city(acc, city)
        if resolved and resolved != city:
            hotels_by_city_checkin[(resolved, ci)].append(hg)

    flights_by_origin_date: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fg in flight_groups:
        origin = fg.get("from", "")
        dt = _date_part(fg.get("depart_date", ""))
        flights_by_origin_date[(origin, dt)].append(fg)
        resolved = _resolve_city(acc, origin)
        if resolved and resolved != origin:
            flights_by_origin_date[(resolved, dt)].append(fg)

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


def _option_trip_count(opt: dict[str, Any]) -> int:
    itins = opt.get("itineraries")
    if not isinstance(itins, list):
        return 0
    return len(itins)


def _itinerary_legs_from_option(opt: dict[str, Any]) -> list[dict[str, str]]:
    """Build ``[{depart, arrive, from, to}, ...]`` — one entry per itinerary in the option."""
    itins = opt.get("itineraries")
    if not isinstance(itins, list):
        return []
    legs: list[dict[str, str]] = []
    for itin in itins:
        if not isinstance(itin, dict):
            continue
        segs = itin.get("segments")
        if not isinstance(segs, list) or not segs:
            continue
        first_seg = segs[0]
        last_seg = segs[-1]
        legs.append({
            "from": _segment_dep_iata(first_seg),
            "to": _segment_arr_iata(last_seg),
            "depart": _segment_dep_at(first_seg),
            "arrive": _segment_arr_at(last_seg),
        })
    return legs


def _partition_flight_groups(
    flight_groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split groups into single-trip options vs multi-trip (e.g. full RT from Amadeus).
    A group may appear in both lists with disjoint option sets.
    Multi groups include ``itinerary_legs`` derived from the first multi-itinerary option.
    """
    simple: list[dict[str, Any]] = []
    multi: list[dict[str, Any]] = []
    for fg in flight_groups:
        opts = [o for o in fg.get("options", []) if isinstance(o, dict)]
        multi_o = [o for o in opts if _option_trip_count(o) >= 2]
        single_o = [o for o in opts if _option_trip_count(o) < 2]
        if single_o:
            simple.append({**fg, "options": single_o})
        if multi_o:
            row: dict[str, Any] = {**fg, "options": multi_o}
            legs = _itinerary_legs_from_option(multi_o[0])
            if legs:
                row["itinerary_legs"] = legs
            multi.append(row)
    return simple, multi


def _resolve_city(acc: dict[str, str], code: str) -> str:
    """Resolve IATA airport code to city code via ``airport_city_codes``; fallback to code itself."""
    c = str(code or "").strip().upper()
    if not c:
        return ""
    return acc.get(c, c)


def _merge_all_airport_city_codes(
    flight_groups: list[dict[str, Any]],
) -> dict[str, str]:
    """Union of ``airport_city_codes`` from every flight group."""
    merged: dict[str, str] = {}
    for fg in flight_groups:
        acc = fg.get("airport_city_codes")
        if isinstance(acc, dict):
            merged.update(acc)
    return merged


def _codes_same_city(
    acc: dict[str, str],
    code_a: str,
    code_b: str,
) -> bool:
    """True if two IATA codes resolve to the same city via ``airport_city_codes``."""
    a = _resolve_city(acc, code_a)
    b = _resolve_city(acc, code_b)
    if not a or not b:
        return False
    return a == b


def _hotel_city_matches_gap_airports(
    acc: dict[str, str],
    hotel_city: str,
    arrival_airport: str,
    departure_airport: str,
) -> bool:
    """
    Hotel city_code matches the gap between two segments when the hotel city resolves
    to the same city as both the arrival airport and the departure airport (via
    ``airport_city_codes``). Falls back to direct code equality when no mapping exists.
    """
    hc = str(hotel_city or "").upper().strip()
    aa = str(arrival_airport or "").upper().strip()
    da = str(departure_airport or "").upper().strip()
    if not hc or not aa or not da:
        return False
    return _codes_same_city(acc, hc, aa) and _codes_same_city(acc, hc, da)


def _offer_matches_trip_endpoints(
    acc: dict[str, str],
    opt: dict[str, Any],
    start_origin: str,
    end_destination: str,
) -> bool:
    """First departure and last arrival city match trip start/end (via airport_city_codes)."""
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
    return _codes_same_city(acc, dep0, start_origin) and _codes_same_city(acc, arr1, end_destination)


def _hotel_fits_itinerary_gap(
    acc: dict[str, str],
    hg: dict[str, Any],
    opt: dict[str, Any],
    gap_index: int,
) -> bool:
    """
    Hotel covers the stay between ``itineraries[gap_index]`` and
    ``itineraries[gap_index + 1]``: last arrival of the earlier itinerary matches
    check-in (date + city); first departure of the later itinerary matches
    check-out (date + city).  City comparison uses ``airport_city_codes``.
    """
    itins = opt.get("itineraries")
    if not isinstance(itins, list) or len(itins) < gap_index + 2:
        return False
    it_before = itins[gap_index]
    it_after = itins[gap_index + 1]
    if not isinstance(it_before, dict) or not isinstance(it_after, dict):
        return False
    segs_before = it_before.get("segments")
    segs_after = it_after.get("segments")
    if (
        not isinstance(segs_before, list) or not segs_before
        or not isinstance(segs_after, list) or not segs_after
    ):
        return False
    last_seg = segs_before[-1]
    first_seg = segs_after[0]
    arr_ap = _segment_arr_iata(last_seg)
    dep_ap = _segment_dep_iata(first_seg)
    arr_dt = _segment_arr_at(last_seg)
    dep_dt = _segment_dep_at(first_seg)
    if not arr_dt or not dep_dt:
        return False
    hc = str(hg.get("city_code", "")).upper().strip()
    ci = str(hg.get("check_in", "")).strip()
    co = str(hg.get("check_out", "")).strip()
    if not hc or not ci or not co:
        return False
    if not _hotel_city_matches_gap_airports(acc, hc, arr_ap, dep_ap):
        return False
    return _date_part(arr_dt) == _date_part(ci) and _date_part(dep_dt) == _date_part(co)


def _enumerate_multi_trip_flight_only(
    acc: dict[str, str],
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
            and _option_trip_count(o) >= 2
            and _offer_matches_trip_endpoints(acc, o, start_origin, end_destination)
        ]
        if not fitted:
            continue
        row = {**fg, "options": fitted}
        out.append({
            "trip_id": str(uuid.uuid4()),
            "flights": [copy.deepcopy(row)],
            "hotels": [],
        })
    return out


def _enumerate_multi_trip_with_hotels(
    acc: dict[str, str],
    multi_fgs: list[dict[str, Any]],
    hotel_groups: list[dict[str, Any]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    """
    One flight group (full multi-trip offer) + hotels slotted into gaps between
    consecutive itineraries.  For an option with N itineraries there are N-1 gaps;
    each gap is independently matched against hotel groups, and the Cartesian
    product of per-gap matches yields the composed trips.
    """
    out: list[dict[str, Any]] = []
    for fg in multi_fgs:
        opts = fg.get("options", [])
        if not isinstance(opts, list):
            continue
        endpoint_ok = [
            o for o in opts
            if isinstance(o, dict)
            and _option_trip_count(o) >= 2
            and _offer_matches_trip_endpoints(acc, o, start_origin, end_destination)
        ]
        if not endpoint_ok:
            continue

        ref_opt = endpoint_ok[0]
        n_gaps = _option_trip_count(ref_opt) - 1
        if n_gaps < 1:
            continue

        hotels_per_gap: list[list[dict[str, Any]]] = []
        for gi in range(n_gaps):
            gap_hotels = [
                hg for hg in hotel_groups
                if isinstance(hg, dict)
                and _hotel_fits_itinerary_gap(acc, hg, ref_opt, gi)
            ]
            hotels_per_gap.append(gap_hotels)

        if not all(hotels_per_gap):
            continue

        for combo in itertools.product(*hotels_per_gap):
            if len(out) >= _MAX_TRIPS:
                return out
            fitted = [
                o for o in endpoint_ok
                if all(
                    _hotel_fits_itinerary_gap(acc, combo[gi], o, gi)
                    for gi in range(n_gaps)
                )
            ]
            if not fitted:
                continue
            row = {**fg, "options": fitted}
            out.append({
                "trip_id": str(uuid.uuid4()),
                "flights": [copy.deepcopy(row)],
                "hotels": [copy.deepcopy(h) for h in combo],
            })
    return out


_MAX_TRIPS = 500


def _flight_edge_ok(
    acc: dict[str, str],
    last_fg: dict[str, Any],
    next_fg: dict[str, Any],
) -> bool:
    """
    Valid direct flight connection: A.to and B.from resolve to the same city
    (via ``airport_city_codes``) and A.arrive_date <= B.depart_date (date-only).
    """
    if not _codes_same_city(acc, str(last_fg.get("to", "")), str(next_fg.get("from", ""))):
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
    acc: dict[str, str],
    flight_groups: list[dict[str, Any]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    """
    When there is no hotel inventory: connect flights where A.to and B.from resolve
    to the same city and A.arrive_date <= B.depart_date (dates only).
    """
    trips: list[dict[str, Any]] = []

    def _dfs(chain_flights: list[dict[str, Any]], used_fg: set[int]) -> None:
        if len(trips) >= _MAX_TRIPS:
            return

        last_fg = chain_flights[-1]
        to_code = str(last_fg.get("to", ""))
        if _codes_same_city(acc, to_code, end_destination):
            trips.append({
                "trip_id": str(uuid.uuid4()),
                "flights": copy.deepcopy(chain_flights),
                "hotels": [],
            })
            return

        for nfg in flight_groups:
            nfg_id = id(nfg)
            if nfg_id in used_fg:
                continue
            if not _flight_edge_ok(acc, last_fg, nfg):
                continue
            chain_flights.append(nfg)
            used_fg.add(nfg_id)
            _dfs(chain_flights, used_fg)
            chain_flights.pop()
            used_fg.discard(nfg_id)

    for fg in flight_groups:
        if _codes_same_city(acc, str(fg.get("from", "")), start_origin):
            _dfs([fg], {id(fg)})

    return trips


def _enumerate_hybrid_chains(
    acc: dict[str, str],
    flight_groups: list[dict[str, Any]],
    hotels_by_city_checkin: dict[tuple[str, str], list[dict[str, Any]]],
    flights_by_origin_date: dict[tuple[str, str], list[dict[str, Any]]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    """
    When some stops have hotel inventory and some do not:
    - If (arrival city, arrival date) has hotel groups: extend with flight -> hotel -> flight
      (next flight departs on hotel check-out).
    - If there are no hotels for that stop: extend with the next flight only when
      _flight_edge_ok (same rules as flight-only mode).
    City comparisons use ``airport_city_codes``.
    """
    trips: list[dict[str, Any]] = []

    def _hotels_for_city_date(city: str, dt: str) -> list[dict[str, Any]]:
        """Lookup hotels matching any code that resolves to the same city."""
        resolved = _resolve_city(acc, city)
        direct = hotels_by_city_checkin.get((city, dt), [])
        if resolved and resolved != city:
            direct = direct + hotels_by_city_checkin.get((resolved, dt), [])
        seen: set[int] = set()
        out: list[dict[str, Any]] = []
        for h in direct:
            hid = id(h)
            if hid not in seen:
                seen.add(hid)
                out.append(h)
        return out

    def _flights_for_city_date(city: str, dt: str) -> list[dict[str, Any]]:
        """Lookup flights departing from any code that resolves to the same city."""
        resolved = _resolve_city(acc, city)
        direct = flights_by_origin_date.get((city, dt), [])
        if resolved and resolved != city:
            direct = direct + flights_by_origin_date.get((resolved, dt), [])
        seen: set[int] = set()
        out: list[dict[str, Any]] = []
        for f in direct:
            fid = id(f)
            if fid not in seen:
                seen.add(fid)
                out.append(f)
        return out

    def _dfs(
        chain_flights: list[dict[str, Any]],
        chain_hotels: list[dict[str, Any]],
        used_fg: set[int],
        used_hg: set[int],
    ) -> None:
        if len(trips) >= _MAX_TRIPS:
            return

        last_fg = chain_flights[-1]
        to_code = str(last_fg.get("to", ""))
        arrive_date = _date_part(last_fg.get("arrive_date", ""))

        if _codes_same_city(acc, to_code, end_destination):
            trips.append({
                "trip_id": str(uuid.uuid4()),
                "flights": copy.deepcopy(chain_flights),
                "hotels": copy.deepcopy(chain_hotels),
            })
            return

        matching_hotels = _hotels_for_city_date(to_code, arrive_date)

        if matching_hotels:
            for hg in matching_hotels:
                if len(trips) >= _MAX_TRIPS:
                    return
                hg_id = id(hg)
                if hg_id in used_hg:
                    continue

                city_code = hg.get("city_code", "")
                check_out = hg.get("check_out", "")
                next_flights = _flights_for_city_date(city_code, check_out)

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
                if len(trips) >= _MAX_TRIPS:
                    return
                nfg_id = id(nfg)
                if nfg_id in used_fg:
                    continue
                if not _flight_edge_ok(acc, last_fg, nfg):
                    continue
                chain_flights.append(nfg)
                used_fg.add(nfg_id)
                _dfs(chain_flights, chain_hotels, used_fg, used_hg)
                chain_flights.pop()
                used_fg.discard(nfg_id)

    for fg in flight_groups:
        if _codes_same_city(acc, str(fg.get("from", "")), start_origin):
            _dfs([fg], [], {id(fg)}, set())

    return trips


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


def _build_locations_dictionary(payload: dict[str, Any]) -> dict[str, str]:
    """
    Map IATA codes to human-readable labels from structured_request trip.legs and trip.stays:
    each leg contributes from -> from_location and to -> to_location; each stay contributes
    city_code -> city. Stays are applied after legs (same key updates to the stay label).
    """
    out: dict[str, str] = {}
    sr = payload.get("structured_request")
    if not isinstance(sr, dict):
        return out
    output = sr.get("output", sr)
    if not isinstance(output, dict):
        return out
    trip = output.get("trip")
    if not isinstance(trip, dict):
        return out

    legs = trip.get("legs")
    if isinstance(legs, list):
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            from_code = str(leg.get("from", "")).strip().upper()
            to_code = str(leg.get("to", "")).strip().upper()
            from_loc = leg.get("from_location")
            to_loc = leg.get("to_location")
            if from_code and isinstance(from_loc, str) and from_loc.strip():
                out[from_code] = from_loc.strip()
            if to_code and isinstance(to_loc, str) and to_loc.strip():
                out[to_code] = to_loc.strip()

    stays = trip.get("stays")
    if isinstance(stays, list):
        for stay in stays:
            if not isinstance(stay, dict):
                continue
            cc = str(stay.get("city_code", "")).strip().upper()
            city = stay.get("city")
            if cc and isinstance(city, str) and city.strip():
                out[cc] = city.strip()

    return out


def _extract_flight_preferences_for_ranking(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy trip-level flight preference fields from structured_request for downstream ranking."""
    sr = payload.get("structured_request")
    if not isinstance(sr, dict):
        return {}
    output = sr.get("output", sr)
    if not isinstance(output, dict):
        return {}
    trip = output.get("trip")
    if not isinstance(trip, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("cabin_preferences", "airline_preferences", "baggage_preference"):
        if key in trip:
            out[key] = copy.deepcopy(trip[key])
    return out


async def compose_trip(
    payload: dict[str, Any],
    *,
    exchange_rate_latest_url: str,
) -> dict[str, Any]:
    """
    Build trips from the inventory response: flight-only when there are no hotels;
    otherwise hybrid (hotel stay at stops where (city, arrival date) has inventory, else
    direct flight connections between flights).
    """
    provider_response = payload.get("provider_response")
    if not isinstance(provider_response, dict):
        logger.warning("No provider_response in payload (id=%s)", payload.get("id"))
        return {"trips": []}

    flight_groups = [fg for fg in provider_response.get("flights", []) if isinstance(fg, dict)]
    hotel_groups = [hg for hg in provider_response.get("hotels", []) if isinstance(hg, dict)]

    if not flight_groups:
        logger.info("No flight groups to compose (id=%s)", payload.get("id"))
        return {"trips": []}

    start_origin, end_destination = _extract_trip_endpoints(payload)
    if not start_origin or not end_destination:
        logger.warning(
            "Cannot determine trip start/end from structured_request (id=%s), "
            "start=%r end=%r",
            payload.get("id"),
            start_origin,
            end_destination,
        )
        return {"trips": []}

    simple_fgs, multi_fgs = _partition_flight_groups(flight_groups)
    acc = _merge_all_airport_city_codes(flight_groups)

    multi_flight_only = _enumerate_multi_trip_flight_only(
        acc, multi_fgs, start_origin, end_destination,
    )

    if not hotel_groups:
        trips = (
            _enumerate_flight_only_chains(acc, simple_fgs, start_origin, end_destination)
            + multi_flight_only
        )
        mode = "flight_only"
    else:
        hotels_by_city_checkin, flights_by_origin_date = _build_indexes(
            acc, simple_fgs, hotel_groups,
        )
        logger.info(
            "Hotels by city check-in: %s",
            hotels_by_city_checkin.keys(),
        )
        fg_out = simple_fgs + multi_fgs
        logger.info("Flight groups: %s", [f"{fg['depart_date']} {fg['arrive_date']} {fg['from']} {fg['to']}" for fg in fg_out])
        trips = (
            _enumerate_hybrid_chains(
                acc, simple_fgs, hotels_by_city_checkin, flights_by_origin_date,
                start_origin, end_destination,
            )
            + _enumerate_multi_trip_with_hotels(
                acc, multi_fgs, hotel_groups, start_origin, end_destination,
            )
            + multi_flight_only
        )
        mode = "hybrid"

    trip_currency = _extract_trip_currency(payload)
    prompt_id = _extract_prompt_id(payload)
    usd_rates = await _fetch_usd_rates(exchange_rate_latest_url)
    locations_dictionary = _build_locations_dictionary(payload)
    flight_prefs = _extract_flight_preferences_for_ranking(payload)
    trip_dicts: dict[str, Any] | None = None
    d0 = provider_response.get("flight_dictionaries")
    if isinstance(d0, dict) and d0:
        trip_dicts = copy.deepcopy(d0)
    for it in trips:
        if flight_prefs:
            for k, v in flight_prefs.items():
                it[k] = v
        if trip_dicts is not None:
            it["flight_dictionaries"] = copy.deepcopy(trip_dicts)
        it["locations_dictionary"] = copy.deepcopy(locations_dictionary)
        it["summary"] = _compute_summary(it, trip_currency)
        it["trip_currency"] = trip_currency.upper()
        if prompt_id:
            it["prompt_id"] = prompt_id
        _annotate_trip_flight_hotel_prices(it, trip_currency, usd_rates)

    logger.info(
        "Composed %d trips (mode=%s) from %d flight groups and %d hotel groups "
        "(start=%s, end=%s, id=%s)",
        len(trips),
        mode,
        len(flight_groups),
        len(hotel_groups),
        start_origin,
        end_destination,
        payload.get("id"),
    )
    return {"trips": trips}
