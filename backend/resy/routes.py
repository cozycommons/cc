"""FastAPI routes for the Resy app. Mounted at /resy (see main.py).

Endpoints:
  POST /resy/onboard          email+password onboarding, mints a ccr_... token
  GET  /resy/me                check a token / describe the Resy profile
  GET  /resy/search             venue search near a location, with slots baked in
  GET  /resy/availability       slots at one venue for a day
  GET  /resy/reservations       the caller's reservations (upcoming | past | all)
  GET  /resy/payment-methods     saved cards, masked ("Visa ....1234")
  POST /resy/book               approval-gated booking write
  POST /resy/cancel             approval-gated cancellation write

Onboarding is one step: the friend provides their Resy email + password
(through the secure vault — never in chat):
  POST /onboard {email, password, label?} -> {"id", "label", "token"}
The token is shown ONCE. The backend logs into Resy immediately and stores
the credentials encrypted; only working credentials are ever stored.

Auth: Authorization: Bearer <personal token> (from /onboard).
Every request resolves the token to exactly one account and only ever touches
that account's Resy data.

Writes (book/cancel) are approval-gated at the agent layer; the backend
enforces per-user scoping and names the masked card on every booking.
"""

from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import accounts
from . import logic
from .accounts import AccountError
from .resy_client import ResyAuthError, ResyClient, ResyError

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

# --- onboarding rate limit: 10 attempts per IP per hour ----------------------
_ONBOARD_ATTEMPTS: dict[str, list[float]] = {}
_ONBOARD_LIMIT = 10
_ONBOARD_WINDOW_S = 3600


def _onboard_rate_check(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _ONBOARD_ATTEMPTS.get(ip, []) if now - t < _ONBOARD_WINDOW_S]
    if len(attempts) >= _ONBOARD_LIMIT:
        raise HTTPException(status_code=429, detail="too many onboarding attempts; try again later")
    attempts.append(now)
    _ONBOARD_ATTEMPTS[ip] = attempts


# --- location -> lat/lng ------------------------------------------------------
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "new york": (40.7128, -73.9352),
    "nyc": (40.7128, -73.9352),
    "manhattan": (40.7831, -73.9712),
    "brooklyn": (40.6782, -73.9442),
    "long island city": (40.7440, -73.9485),
    "lic": (40.7440, -73.9485),
    "queens": (40.7282, -73.7949),
    "los angeles": (34.0522, -118.2437),
    "la": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "san francisco": (37.7749, -122.4194),
    "sf": (37.7749, -122.4194),
    "miami": (25.7617, -80.1918),
    "austin": (30.2672, -97.7431),
    "seattle": (47.6062, -122.3321),
    "boston": (42.3601, -71.0589),
    "denver": (39.7392, -104.9903),
    "atlanta": (33.7490, -84.3880),
    "dallas": (32.7767, -96.7970),
    "houston": (29.7605, -95.3698),
    "philadelphia": (39.9526, -75.1652),
    "washington": (38.9072, -77.0369),
    "dc": (38.9072, -77.0369),
    "las vegas": (36.1699, -115.1398),
    "vegas": (36.1699, -115.1398),
    "nashville": (36.1627, -86.7816),
    "portland": (45.5152, -122.6784),
    "san diego": (32.7157, -117.1611),
}


def _coords_for(location: str | None, lat: float | None,
                lng: float | None) -> tuple[float, float]:
    if lat is not None and lng is not None:
        return lat, lng
    needle = (location or "").strip().lower()
    for city, coords in _CITY_COORDS.items():
        if city in needle:
            return coords
    # Default to NYC (Resy's densest market) rather than failing.
    return _CITY_COORDS["new york"]


def _supabase(request: Request):
    return request.app.state.supabase


def _account(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),  # noqa: B008
) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return accounts.get_account_by_token(_supabase(request), creds.credentials)
    except AccountError:
        raise HTTPException(status_code=401, detail="invalid token")


def _client(request: Request, account: dict) -> ResyClient:
    return accounts.make_client_for_account(_supabase(request), account)


def _resy_errors(fn):
    """Map Resy/logic exceptions to HTTP statuses."""
    try:
        return fn()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ResyAuthError as e:
        raise HTTPException(status_code=401, detail=f"{e} (re-onboard)")
    except ResyError as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- models ------------------------------------------------------------------
class OnboardBody(BaseModel):
    email: str = Field(description="Resy account email")
    password: str = Field(description="Resy account password")
    label: str = Field(default="resy", max_length=80)


class BookBody(BaseModel):
    venue_id: int = Field(description="Numeric Resy venue id")
    date: str = Field(description="Reservation date, YYYY-MM-DD")
    party_size: int = Field(default=2, ge=1, le=20)
    desired_time: str | None = Field(
        default=None, description='Preferred slot, "HH:MM" (e.g. "19:30")'
    )
    slot_token: str | None = Field(
        default=None,
        description="Exact slot config token (rgs://...) from /availability; "
        "takes precedence over desired_time",
    )
    payment_method_id: int | None = Field(
        default=None,
        description="Saved card id; defaults to the account default",
    )


class CancelBody(BaseModel):
    resy_token: str | None = Field(
        default=None, description="resy_token (rr://...) of the reservation"
    )
    reservation_id: int | None = Field(
        default=None, description="Numeric confirmation number (alternative)"
    )


# --- endpoints ---------------------------------------------------------------
@router.post("/onboard")
def onboard(body: OnboardBody, request: Request):
    """Connect a Resy account and mint a personal API token.

    Provide the Resy email + password through the secure vault (never in
    chat). The backend logs into Resy immediately — only working credentials
    are stored. The returned token is shown ONCE.
    """
    ip = (request.client.host if request.client else "unknown") or "unknown"
    _onboard_rate_check(ip)
    try:
        return accounts.create_account(
            _supabase(request), body.label, body.email, body.password
        )
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
def me(request: Request, account: dict = Depends(_account)):  # noqa: B008
    """The caller's Resy profile behind their token."""
    client = _client(request, account)
    user = _resy_errors(client.get_user)
    return {
        "id": account["id"],
        "label": account["label"],
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "email": user.get("em_address"),
    }


@router.get("/search")
def search(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    query: str = Query(default="", description="Venue name/cuisine query"),
    location: str | None = Query(
        default=None, description='e.g. "Long Island City", "manhattan"'
    ),
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    day: str = Query(
        default_factory=lambda: date.today().isoformat(),
        description="Day to bake slots for, YYYY-MM-DD",
    ),
    party_size: int = Query(default=2, ge=1, le=20),
):
    """Search Resy venues near a location, with the day's slots baked in."""
    client = _client(request, account)
    lat_v, lng_v = _coords_for(location, lat, lng)
    return _resy_errors(
        lambda: logic.search_restaurants(
            client, query, lat_v, lng_v, day, party_size
        )
    )


@router.get("/availability")
def availability(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    venue_id: int = Query(description="Numeric Resy venue id"),
    day: str = Query(description="YYYY-MM-DD"),
    party_size: int = Query(default=2, ge=1, le=20),
):
    """Available slots at one venue for a day."""
    client = _client(request, account)
    return _resy_errors(
        lambda: logic.check_availability(client, venue_id, day, party_size)
    )


@router.get("/reservations")
def reservations(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    scope: str = Query(
        default="upcoming", description="upcoming | past | all"
    ),
):
    """The caller's Resy reservations."""
    client = _client(request, account)
    return _resy_errors(lambda: logic.list_reservations(client, scope))


@router.get("/payment-methods")
def payment_methods(
    request: Request, account: dict = Depends(_account)  # noqa: B008
):
    """The caller's saved Resy cards, masked ("Visa ....1234")."""
    client = _client(request, account)
    return _resy_errors(lambda: logic.list_payment_methods(client))


@router.post("/book")
def book(body: BookBody, request: Request, account: dict = Depends(_account)):  # noqa: B008
    """Book a table. Approval-gated at the agent layer: the agent confirms
    venue, date, time, party size, and the masked card with the user before
    calling. The response names the masked card used."""
    client = _client(request, account)
    return _resy_errors(
        lambda: logic.book_table(
            client,
            body.venue_id,
            body.date,
            body.party_size,
            desired_time=body.desired_time,
            slot_token=body.slot_token,
            payment_method_id=body.payment_method_id,
        )
    )


@router.post("/cancel")
def cancel(
    body: CancelBody, request: Request, account: dict = Depends(_account)  # noqa: B008
):
    """Cancel a reservation by resy_token or numeric confirmation number.
    Approval-gated at the agent layer."""
    client = _client(request, account)
    return _resy_errors(
        lambda: logic.cancel_reservation(
            client,
            resy_token=body.resy_token,
            reservation_id=body.reservation_id,
        )
    )
