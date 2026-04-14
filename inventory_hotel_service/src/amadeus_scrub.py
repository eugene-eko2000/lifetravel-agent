"""
Keep only Amadeus hotel fields referenced by lifetravel-agent README schemas (§12)
and downstream ranking, trip_composer, and frontends.
"""

from __future__ import annotations

from typing import Any


def _scrub_flight_dictionaries(d: dict[str, Any]) -> dict[str, Any]:
    """Same subset as inventory_flight_service (passthrough from provider_flight_response)."""
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


def scrub_flight_dictionaries(d: dict[str, Any]) -> dict[str, Any]:
    """Public alias for hotel service `process_incoming_message` flight_dictionaries passthrough."""
    return _scrub_flight_dictionaries(d)


def _scrub_hotel_price_variations_average(avg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in avg.items():
        if k in ("total", "base"):
            out[k] = v
        elif k.endswith("_trip_currency") or k.endswith("_itinerary_currency"):
            out[k] = v
    return out


def _scrub_hotel_price(p: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in p.items():
        if k in ("currency", "grandTotal", "total", "base"):
            out[k] = v
        elif k.endswith("_trip_currency"):
            out[k] = v
    var = p.get("variations")
    if isinstance(var, dict):
        vout: dict[str, Any] = {}
        avg = var.get("average")
        if isinstance(avg, dict):
            vout["average"] = _scrub_hotel_price_variations_average(avg)
        if vout:
            out["variations"] = vout
    return out


def _scrub_room_type_estimated(te: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("category", "bedType", "beds"):
        if k in te:
            out[k] = te[k]
    return out


def _scrub_hotel_room(room: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "type" in room:
        out["type"] = room["type"]
    desc = room.get("description")
    if isinstance(desc, dict):
        text = desc.get("text")
        if isinstance(text, str):
            out["description"] = {"text": text}
    te = room.get("typeEstimated")
    if isinstance(te, dict):
        te_out = _scrub_room_type_estimated(te)
        if te_out:
            out["typeEstimated"] = te_out
    return out


def _scrub_cancellation_policy(c: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("type", "deadline", "numberOfNights", "policyType"):
        if k in c:
            out[k] = c[k]
    return out


def _scrub_hotel_policies(pol: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "paymentType" in pol:
        out["paymentType"] = pol["paymentType"]
    ref = pol.get("refundable")
    if isinstance(ref, dict):
        cr = ref.get("cancellationRefund")
        if isinstance(cr, str):
            out["refundable"] = {"cancellationRefund": cr}
    can = pol.get("cancellation")
    if isinstance(can, dict):
        out["cancellation"] = _scrub_cancellation_policy(can)
    cans = pol.get("cancellations")
    if isinstance(cans, list):
        out["cancellations"] = [
            _scrub_cancellation_policy(x) for x in cans if isinstance(x, dict)
        ]
    prep = pol.get("prepay")
    if isinstance(prep, dict):
        pout: dict[str, Any] = {}
        if "deadline" in prep:
            pout["deadline"] = prep["deadline"]
        ap = prep.get("acceptedPayments")
        if isinstance(ap, dict):
            ap_out: dict[str, Any] = {}
            for key in ("creditCards", "methods"):
                if isinstance(ap.get(key), list):
                    ap_out[key] = ap[key]
            if ap_out:
                pout["acceptedPayments"] = ap_out
        if pout:
            out["prepay"] = pout
    return out


def _scrub_hotel_rate_offer(offer: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("checkInDate", "checkOutDate", "check_in", "check_out", "rateCode"):
        if k in offer:
            out[k] = offer[k]
    if isinstance(offer.get("price"), dict):
        out["price"] = _scrub_hotel_price(offer["price"])
    g = offer.get("guests")
    if isinstance(g, dict) and "adults" in g:
        out["guests"] = {"adults": g["adults"]}
    if isinstance(offer.get("room"), dict):
        r = _scrub_hotel_room(offer["room"])
        if r:
            out["room"] = r
    ri = offer.get("roomInformation")
    if isinstance(ri, dict):
        ri_out: dict[str, Any] = {}
        if "description" in ri and isinstance(ri["description"], str):
            ri_out["description"] = ri["description"]
        if "type" in ri:
            ri_out["type"] = ri["type"]
        te = ri.get("typeEstimated")
        if isinstance(te, dict):
            teo = _scrub_room_type_estimated(te)
            if teo:
                ri_out["typeEstimated"] = teo
        if ri_out:
            out["roomInformation"] = ri_out
    if isinstance(offer.get("policies"), dict):
        po = _scrub_hotel_policies(offer["policies"])
        if po:
            out["policies"] = po
    rf = offer.get("rateFamilyEstimated")
    if isinstance(rf, dict) and isinstance(rf.get("code"), str):
        out["rateFamilyEstimated"] = {"code": rf["code"]}
    comm = offer.get("commission")
    if isinstance(comm, dict) and "percentage" in comm:
        out["commission"] = {"percentage": comm["percentage"]}
    return out


def _scrub_hotel_geo(h: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in (
        "hotelId",
        "name",
        "chain",
        "brand",
        "latitude",
        "longitude",
        "rating",
        "amenities",
        "city_code",
        "cityCode",
        "city",
        "check_in",
        "check_out",
        "checkIn",
        "checkOut",
    ):
        if k in h:
            out[k] = h[k]
    dist = h.get("distance")
    if isinstance(dist, dict) and "value" in dist:
        out["distance"] = {"value": dist["value"]}
    return out


def scrub_hotel_offer(offer: dict[str, Any]) -> dict[str, Any]:
    """Subset of Amadeus Hotel Search / Offers `data[]` item."""
    out: dict[str, Any] = {}
    for k in ("available", "error"):
        if k in offer:
            out[k] = offer[k]
    errs = offer.get("errors")
    if errs is not None:
        out["errors"] = errs
    if isinstance(offer.get("hotel"), dict):
        out["hotel"] = _scrub_hotel_geo(offer["hotel"])
    offs = offer.get("offers")
    if isinstance(offs, list):
        out["offers"] = [_scrub_hotel_rate_offer(x) for x in offs if isinstance(x, dict)]
    if isinstance(offer.get("_stay"), dict):
        out["_stay"] = dict(offer["_stay"])
    if isinstance(offer.get("_ranking"), dict):
        out["_ranking"] = offer["_ranking"]
    return out
