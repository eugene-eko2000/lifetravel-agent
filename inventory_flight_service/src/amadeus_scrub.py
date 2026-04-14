"""
Keep only Amadeus flight fields referenced by lifetravel-agent README schemas (§11)
and downstream ranking, trip_composer, and frontends.
"""

from __future__ import annotations

from typing import Any


def _scrub_flight_endpoint(ep: dict[str, Any]) -> dict[str, Any]:
    keys = ("iataCode", "at", "terminal", "cityName", "city")
    return {k: ep[k] for k in keys if k in ep and ep[k] is not None}


def _scrub_included_bags(b: dict[str, Any]) -> dict[str, Any]:
    keys = ("quantity", "weight", "maximumWeight", "maxWeight", "weightUnit", "unit")
    return {k: b[k] for k in keys if k in b}


def _scrub_fare_details(fd: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("segmentId", "cabin"):
        if k in fd:
            out[k] = fd[k]
    for bag_key in ("includedCheckedBags", "checkedBags", "includedCabinBags", "cabinBags"):
        raw = fd.get(bag_key)
        if isinstance(raw, dict):
            out[bag_key] = _scrub_included_bags(raw)
    return out


def _scrub_traveler_pricing(tp: dict[str, Any]) -> dict[str, Any]:
    fds = tp.get("fareDetailsBySegment")
    if not isinstance(fds, list):
        return {}
    cleaned = [_scrub_fare_details(x) for x in fds if isinstance(x, dict)]
    return {"fareDetailsBySegment": cleaned}


def _scrub_pricing_options(po: dict[str, Any]) -> dict[str, Any]:
    return {k: po[k] for k in ("refundableFare", "includedCheckedBagsOnly") if k in po}


def _scrub_flight_price(p: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in p.items():
        if k in ("currency", "grandTotal", "total", "base", "amount"):
            out[k] = v
        elif k.endswith("_trip_currency"):
            out[k] = v
    return out


def _scrub_flight_segment(seg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("id", "segmentId", "duration", "carrierCode", "number"):
        if k in seg:
            out[k] = seg[k]
    dep = seg.get("departure")
    if isinstance(dep, dict):
        out["departure"] = _scrub_flight_endpoint(dep)
    arr = seg.get("arrival")
    if isinstance(arr, dict):
        out["arrival"] = _scrub_flight_endpoint(arr)
    op = seg.get("operating")
    if isinstance(op, dict):
        op_out = {k: op[k] for k in ("carrierCode", "carrier") if k in op}
        if op_out:
            out["operating"] = op_out
    return out


def _scrub_flight_itinerary(itin: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "duration" in itin:
        out["duration"] = itin["duration"]
    segs = itin.get("segments")
    if isinstance(segs, list):
        out["segments"] = [_scrub_flight_segment(s) for s in segs if isinstance(s, dict)]
    return out


def scrub_flight_offer(opt: dict[str, Any]) -> dict[str, Any]:
    """Subset of a single Amadeus Flight Offers Search offer (`data[]` item)."""
    out: dict[str, Any] = {}
    if "id" in opt:
        out["id"] = opt["id"]
    itins = opt.get("itineraries")
    if isinstance(itins, list):
        out["itineraries"] = [_scrub_flight_itinerary(i) for i in itins if isinstance(i, dict)]
    if isinstance(opt.get("price"), dict):
        out["price"] = _scrub_flight_price(opt["price"])
    tps = opt.get("travelerPricings")
    if isinstance(tps, list):
        out["travelerPricings"] = [_scrub_traveler_pricing(x) for x in tps if isinstance(x, dict)]
    if isinstance(opt.get("pricingOptions"), dict):
        po = _scrub_pricing_options(opt["pricingOptions"])
        if po:
            out["pricingOptions"] = po
    for k in ("flight_kind", "round_trip_pair_id"):
        if k in opt:
            out[k] = opt[k]
    if isinstance(opt.get("_ranking"), dict):
        out["_ranking"] = opt["_ranking"]
    return out


def scrub_flight_dictionaries(d: dict[str, Any]) -> dict[str, Any]:
    """Subset of Amadeus `dictionaries` (locations + carriers) merged into flight_dictionaries."""
    out: dict[str, Any] = {}
    locs = d.get("locations")
    if isinstance(locs, dict):
        loc_out: dict[str, Any] = {}
        for code, v in locs.items():
            if not isinstance(v, dict):
                continue
            entry: dict[str, Any] = {}
            for kk in ("cityCode", "countryCode"):
                if kk in v:
                    entry[kk] = v[kk]
            if entry:
                loc_out[code] = entry
        if loc_out:
            out["locations"] = loc_out
    carriers = d.get("carriers")
    if isinstance(carriers, dict):
        car_out = {k: v for k, v in carriers.items() if isinstance(v, str)}
        if car_out:
            out["carriers"] = car_out
    return out
