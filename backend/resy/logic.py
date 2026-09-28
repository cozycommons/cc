"""Resy adhoc logic: pure functions over a ResyClient (no framework code).

Read helpers slim Resy's wire shapes; book_table / cancel_reservation are the
two approval-gated writes. Slot times come back as restaurant-local "HH:MM:SS"
with no timezone offset — they are read off the string directly, never
TZ-shifted.
"""

from __future__ import annotations

from datetime import date as _date


def _hhmm(value: str | None) -> str | None:
    """'2026-09-28 19:30:00' or '19:30:00' -> '19:30'.

    Never parsed as a datetime (no TZ shift); the time is read off the string.
    """
    if not value:
        return None
    time_part = str(value).strip().split()[-1]  # drop any date prefix
    parts = time_part.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{parts[1]}"
    return str(value)


def _parse_day(value: str, name: str = "day") -> _date:
    from datetime import datetime

    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise ValueError(f"{name} must be YYYY-MM-DD")


def _slim_slot(slot: dict) -> dict:
    config = slot.get("config") or {}
    slot_date = slot.get("date") or {}
    payment = slot.get("payment") or {}
    return {
        "token": config.get("token"),
        "type": config.get("type"),
        "start": _hhmm(slot_date.get("start")),
        "end": _hhmm(slot_date.get("end")),
        "cancellation_fee": payment.get("cancellation_fee"),
        "deposit_fee": payment.get("deposit_fee"),
    }


def _slim_venue(entry: dict, include_slots: bool = True) -> dict:
    venue = entry.get("venue") or {}
    loc = venue.get("location") or {}
    vid = (venue.get("id") or {}).get("resy")
    out = {
        "venue_id": vid,
        "name": venue.get("name"),
        "neighborhood": loc.get("neighborhood"),
        "city": loc.get("locality"),
        "cuisine": venue.get("type") or venue.get("cuisine"),
        "price_range": venue.get("price_range"),
        "rating": venue.get("rating"),
        "url_slug": venue.get("url_slug"),
    }
    if include_slots:
        slots = entry.get("slots") or []
        out["slots"] = [_slim_slot(s) for s in slots if isinstance(s, dict)]
        out["available_times"] = [
            s["start"] for s in out["slots"] if s.get("start")
        ]
    return out


def masked_card_label(payment: dict) -> str:
    """'Visa ....1234' style label from a Resy payment method dict."""
    brand = str(payment.get("brand") or "Card").strip().title()
    last = (
        payment.get("last_four")
        or payment.get("last4")
        or payment.get("display_number")
        or ""
    )
    last = "".join(ch for ch in str(last) if ch.isdigit())[-4:]
    return f"{brand} ....{last}" if last else brand


def search_restaurants(client, query: str, lat: float, lng: float, day: str,
                       party_size: int) -> list:
    """Venue search near (lat, lng) with that day's slots baked in."""
    _parse_day(day)
    if party_size < 1 or party_size > 20:
        raise ValueError("party_size must be 1..20")
    venues = client.search(query or "", lat, lng, day, party_size)
    return [_slim_venue(v) for v in venues if isinstance(v, dict)]


def check_availability(client, venue_id: int, day: str, party_size: int) -> dict:
    """Available slots at one venue for a day."""
    _parse_day(day)
    if party_size < 1 or party_size > 20:
        raise ValueError("party_size must be 1..20")
    try:
        vid = int(venue_id)
    except (TypeError, ValueError):
        raise ValueError("venue_id must be numeric")
    slots = client.find_slots(vid, day, party_size)
    slim = [_slim_slot(s) for s in slots if isinstance(s, dict)]
    venue = client.get_venue(vid) or {}
    loc = venue.get("location") or {}
    return {
        "venue_id": vid,
        "venue_name": venue.get("name"),
        "neighborhood": loc.get("neighborhood"),
        "day": day,
        "party_size": party_size,
        "slots": slim,
        "available_times": [s["start"] for s in slim if s.get("start")],
    }


def list_reservations(client, scope: str = "upcoming") -> list:
    """The user's reservations; Resy's own scope param is a no-op so the
    upcoming/past split is filtered client-side on the reservation day."""
    if scope not in ("upcoming", "past", "all"):
        raise ValueError("scope must be upcoming | past | all")
    today = _date.today().isoformat()
    out = []
    for item in client.get_reservations():
        r = item.get("reservation") or {}
        venue = item.get("venue") or {}
        day = str(r.get("day") or "")
        status = r.get("status") or {}
        if status.get("no_show"):
            state = "no_show"
        elif status.get("finished"):
            state = "finished"
        elif day and day < today:
            state = "past"
        else:
            state = "upcoming"
        if scope == "upcoming" and state != "upcoming":
            continue
        if scope == "past" and state == "upcoming":
            continue
        out.append(
            {
                "resy_token": r.get("resy_token"),
                "reservation_id": r.get("reservation_id"),
                "venue_id": (r.get("venue") or {}).get("id"),
                "venue_name": venue.get("name") or "",
                "day": day,
                "time": _hhmm(r.get("time_slot")),
                "party_size": r.get("num_seats"),
                "status": state,
                "cancellable": (r.get("cancellation") or {}).get("allowed") is True,
            }
        )
    return out


def list_payment_methods(client) -> list:
    """Saved cards, masked — the backend never sees full card numbers."""
    user = client.get_user()
    methods = user.get("payment_methods") or []
    out = []
    for pm in methods if isinstance(methods, list) else []:
        if not isinstance(pm, dict):
            continue
        out.append(
            {
                "id": pm.get("id"),
                "label": masked_card_label(pm),
                "brand": pm.get("brand"),
                "last_four": pm.get("last_four")
                or pm.get("last4")
                or pm.get("display_number"),
                "exp_month": pm.get("exp_month"),
                "exp_year": pm.get("exp_year"),
                "is_default": pm.get("is_default") is True,
            }
        )
    return out


def _resolve_payment_method(client, payment_method_id: int | None) -> dict:
    methods = list_payment_methods(client)
    if not methods:
        raise ValueError(
            "No payment method on file. Add one at resy.com/account before booking."
        )
    if payment_method_id is not None:
        for pm in methods:
            if pm["id"] == payment_method_id:
                return pm
        raise ValueError(f"unknown payment_method_id {payment_method_id}")
    for pm in methods:
        if pm["is_default"]:
            return pm
    return methods[0]


def book_table(client, venue_id: int, day: str, party_size: int,
               desired_time: str | None = None,
               slot_token: str | None = None,
               payment_method_id: int | None = None) -> dict:
    """Approval-gated write: book one slot.

    Pick the slot either by its config token (from check_availability) or by
    venue_id + desired_time ("HH:MM"). Resolves the book_token via
    /3/details, then books. Returns the confirmation, naming the masked card
    charged/held.
    """
    _parse_day(day, "date")
    if party_size < 1 or party_size > 20:
        raise ValueError("party_size must be 1..20")
    try:
        vid = int(venue_id)
    except (TypeError, ValueError):
        raise ValueError("venue_id must be numeric")

    token = (slot_token or "").strip() or None
    slot_start = None
    if token is None:
        if not desired_time:
            raise ValueError("pass slot_token or desired_time (HH:MM)")
        want = _hhmm(desired_time)
        slots = [_slim_slot(s) for s in client.find_slots(vid, day, party_size)
                 if isinstance(s, dict)]
        matches = [s for s in slots if s.get("start") == want and s.get("token")]
        if not matches:
            available = [s["start"] for s in slots if s.get("start")]
            raise ValueError(
                f"no slot at {want} on {day}; "
                f"available: {', '.join(available) if available else 'none'}"
            )
        token = matches[0]["token"]
        slot_start = matches[0]["start"]

    details = client.get_book_details(token, day, party_size)
    book_token = (details.get("book_token") or {}).get("value")
    if not book_token:
        raise ValueError("Resy did not return a book_token for that slot")
    venue_name = (details.get("venue") or {}).get("name")

    pm = _resolve_payment_method(client, payment_method_id)
    result = client.book(book_token, pm["id"])
    return {
        "resy_token": result.get("resy_token"),
        "reservation_id": result.get("reservation_id"),
        "venue_id": vid,
        "venue_name": venue_name,
        "date": result.get("day") or day,
        "time": _hhmm(result.get("time_slot")) or slot_start,
        "party_size": result.get("num_seats") or party_size,
        "payment_method": pm["label"],
        "payment_method_id": pm["id"],
    }


def cancel_reservation(client, resy_token: str | None = None,
                       reservation_id: int | str | None = None) -> dict:
    """Approval-gated write: cancel by resy_token or numeric confirmation id."""
    token = (resy_token or "").strip() or None
    if token is None:
        if reservation_id is None:
            raise ValueError("pass resy_token or reservation_id")
        needle = str(reservation_id)
        match = next(
            (
                item.get("reservation") or {}
                for item in client.get_reservations()
                if str((item.get("reservation") or {}).get("reservation_id"))
                == needle
            ),
            None,
        )
        if not match or not match.get("resy_token"):
            raise ValueError(
                f"no reservation found with confirmation number {needle}"
            )
        token = match["resy_token"]
    client.cancel(token)
    return {"cancelled": True, "resy_token": token}
