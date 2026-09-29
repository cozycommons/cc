"""Beli recs + bookmark business logic.

Python port of the beli-recs TypeScript endpoints (api/recs.ts, api/bookmark.ts)
plus the caption-mining helpers from beli_eats_watch.py. Pure functions take a
BeliClient; nothing here knows about HTTP frameworks or tenants.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .beli_client import BeliClient, results_of

TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# name matching (bookmark.ts)
# ---------------------------------------------------------------------------

_AMBIGUOUS_STOPWORDS = {
    "beli", "eats", "nyc", "top", "best", "new", "list", "food", "foodie",
    "restaurant", "restaurants", "spots", "guide", "part", "giveaway",
}


def norm(s) -> str:
    """Lowercase alphanumeric only: "Table Mercato" -> "tablemercato"."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower().replace("&", "and"))


def norm_loose(s) -> str:
    return str(s or "").lower().strip()


def confident_match(search_name: str, businesses: list):
    """Confidence gate. Returns (business, score) or None.

    Accepts exact normalized equality, or one normalized name containing the
    other when the length ratio is sane (handles "Lucali" vs "Lucali Bk").
    """
    target = norm(search_name)
    if not target:
        return None
    best = None
    for b in businesses:
        cand = norm((b or {}).get("name"))
        if not cand:
            continue
        score = 0.0
        if cand == target:
            score = 1.0
        elif (target in cand or cand in target) and (
            min(len(cand), len(target)) / max(len(cand), len(target)) >= 0.6
        ):
            score = 0.7
        if score > (best[1] if best else 0):
            best = (b, score)
    return best if best and best[1] >= 0.7 else None


# ---------------------------------------------------------------------------
# day / time helpers (recs.ts)
# ---------------------------------------------------------------------------

DAY_NAMES = [
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
]


def et_now() -> datetime:
    return datetime.now(TZ)


def resolve_day(day_param: str | None) -> str:
    """YYYY-MM-DD or English day name -> YYYY-MM-DD (ET). Default: today."""
    now = et_now()
    if not day_param:
        return now.strftime("%Y-%m-%d")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", day_param):
        return day_param
    idx = DAY_NAMES.index(norm_loose(day_param)[:9]) if norm_loose(day_param)[:9] in DAY_NAMES else -1
    if idx == -1:
        raise ValueError(f"Unrecognized day: {day_param}")
    from datetime import timedelta

    # JS getDay(): Sunday=0..Saturday=6; python weekday(): Monday=0..Sunday=6
    js_day = (now.weekday() + 1) % 7
    delta = (idx - js_day) % 7  # today if it matches
    return (now + timedelta(days=delta)).strftime("%Y-%m-%d")


def parse_time_to_mins(t: str | None) -> int | None:
    if not t:
        return None
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", norm_loose(t))
    if not m:
        return None
    h, minute, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h * 60 + minute


def fmt_mins(mins: int) -> str:
    h, m = (mins // 60) % 24, mins % 60
    ap = "PM" if h >= 12 else "AM"
    h = 12 if h % 12 == 0 else h % 12
    return f"{h}:{m:02d} {ap}"


def entry_covers(e: dict, day_idx: int, mins: int | None) -> bool:
    """Day numbering: 0=Sunday..6=Saturday (JS/Capacitor convention)."""
    open_m = parse_time_to_mins(e.get("open_time"))
    close_m = parse_time_to_mins(e.get("close_time"))
    if open_m is None or close_m is None:
        return False
    overnight = close_m <= open_m or e.get("close_day") != e.get("open_day")
    if mins is None:
        return e.get("open_day") == day_idx or (overnight and e.get("close_day") == day_idx)
    if not overnight:
        return e.get("open_day") == day_idx and open_m <= mins < close_m
    return (e.get("open_day") == day_idx and mins >= open_m) or (
        e.get("close_day") == day_idx and mins < close_m
    )


def hours_summary(sets: list, day_idx: int, mins: int | None) -> dict:
    if not sets:
        return {"label": None, "open": None}
    todays = [e for e in sets if e.get("open_day") == day_idx]
    parts = []
    for e in todays:
        o, c = parse_time_to_mins(e.get("open_time")), parse_time_to_mins(e.get("close_time"))
        if o is not None and c is not None:
            parts.append(f"{fmt_mins(o)} – {fmt_mins(c)}")
    label = ", ".join(parts) or None
    if mins is None:
        open_now = bool(todays) or any(
            e.get("close_day") == day_idx
            and (parse_time_to_mins(e.get("close_time")) or 0)
            > (parse_time_to_mins(e.get("open_time")) or 0)
            for e in sets
        )
    else:
        open_now = any(entry_covers(e, day_idx, mins) for e in sets)
    return {"label": label, "open": open_now}


# ---------------------------------------------------------------------------
# availability parsing (defensive: shape not pinned in spec)
# ---------------------------------------------------------------------------

_TIME_LIKE_RE = re.compile(r"^\d{1,2}:\d{2}(\s?[AP]M)?$", re.IGNORECASE)


def _collect_time_likes(node, out: list) -> None:
    if isinstance(node, str):
        if _TIME_LIKE_RE.match(node.strip()):
            out.append(node.strip())
        return
    if isinstance(node, list):
        for v in node:
            _collect_time_likes(v, out)
        return
    if isinstance(node, dict):
        for v in node.values():
            _collect_time_likes(v, out)


def slots_for_business(payload, business_id) -> list:
    out: list = []
    id_str = str(business_id)

    def scan(node):
        if isinstance(node, list):
            import json as _json

            for item in node:
                if id_str in _json.dumps(item, default=str):
                    _collect_time_likes(item, out)
        elif isinstance(node, dict):
            for k, v in node.items():
                if id_str in str(k):
                    _collect_time_likes(v, out)
                else:
                    scan(v)

    scan(payload)
    seen = list(dict.fromkeys(out))
    return seen[:12]


# ---------------------------------------------------------------------------
# recs service
# ---------------------------------------------------------------------------

def _logged_in_uuid(client: BeliClient) -> str:
    me = client.api_with_reauth("/api/user/logged-in/")
    objs = results_of(me)
    obj = objs[0] if objs else (me if isinstance(me, dict) else {})
    uuid = (obj or {}).get("uuid") or (obj or {}).get("id")
    if not uuid:
        raise ValueError("could not resolve logged-in user uuid")
    return str(uuid)


def get_recs(
    client: BeliClient,
    neighborhood: str,
    day: str | None = None,
    time: str | None = None,
    table_size: int = 2,
    limit: int = 10,
) -> dict:
    """Bookmarks (ranked by the user's scores) first, then Beli trending."""
    if not (neighborhood or "").strip():
        raise ValueError("neighborhood is required")
    date_str = resolve_day(day)
    time_mins = parse_time_to_mins(time)
    table_size = max(1, int(table_size or 2))
    limit = min(20, max(1, int(limit or 10)))

    user_uuid = _logged_in_uuid(client)
    bm_raw = client.api_with_reauth(f"/api/get-bookmark/?user={user_uuid}&category=RES")
    tr_raw = client.api_with_reauth(f"/api/trending/{user_uuid}/")
    bookmark_items = results_of(bm_raw)
    trending_items = results_of(tr_raw)

    def biz_of(item):
        return (item or {}).get("business") or item or {}

    def score_of(item):
        item = item or {}
        b = item.get("business") or {}
        return item.get("score") or item.get("rank_score") or item.get("rating") or b.get("score") or 0

    nq = norm_loose(neighborhood)

    def in_area(b):
        for f in (b.get("neighborhood"), b.get("borough"), b.get("city")):
            nf = norm_loose(f)
            if nf and (nq in nf or nf in nq):
                return True
        return False

    bookmarked = sorted(
        ({"item": it, "b": biz_of(it)} for it in bookmark_items if (biz_of(it) or {}).get("id") and in_area(biz_of(it))),
        key=lambda x: score_of(x["item"]),
        reverse=True,
    )
    seen = {f["b"]["id"] for f in bookmarked}
    trending = [
        {"item": it, "b": biz_of(it)}
        for it in trending_items
        if (biz_of(it) or {}).get("id") and in_area(biz_of(it)) and biz_of(it)["id"] not in seen
    ]
    finalists = (bookmarked + trending)[:limit]

    # day index 0=Sunday..6=Saturday
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    day_idx = (dt.weekday() + 1) % 7

    for f in finalists:
        b = f["b"]
        if not b.get("businesshours_set") and b.get("id"):
            try:
                detail = client.api_with_reauth(f"/api/business/?id={b['id']}")
                d0 = results_of(detail)
                d = d0[0] if d0 else {}
                full = (d.get("business") or d) if isinstance(d, dict) else {}
                f["b"] = {**b, **(full if isinstance(full, dict) else {})}
            except Exception:
                pass

    avail_payload = None
    try:
        body: dict = {
            "business_ids": [f["b"]["id"] for f in finalists],
            "date": date_str,
            "table_size": table_size,
        }
        if time:
            body["time"] = time
        avail_payload = client.api_with_reauth(
            "/api/businesses-res-availability/", method="POST", body=body
        )
    except Exception:
        pass  # availability optional; recs still useful without it

    recs = []
    for i, f in enumerate(finalists):
        b = f["b"]
        summary = hours_summary(b.get("businesshours_set") or [], day_idx, time_mins)
        platforms = list((b.get("reservation_platforms") or {}).keys())
        recs.append(
            {
                "name": b.get("name"),
                "id": b.get("id"),
                "source": "bookmark" if i < len(bookmarked) else "trending",
                "neighborhood": b.get("neighborhood"),
                "borough": b.get("borough"),
                "cuisines": b.get("cuisines") or [],
                "price": b.get("price"),
                "hours_today": summary["label"],
                "open_at_time": summary["open"],
                "reservation": {
                    "has_links": bool(b.get("has_res_links") or platforms),
                    "platforms": platforms,
                    "slots": slots_for_business(avail_payload, b["id"]) if avail_payload else [],
                },
            }
        )
    return {
        "neighborhood": neighborhood,
        "date": date_str,
        "time": time,
        "table_size": table_size,
        "recs": recs,
    }


# ---------------------------------------------------------------------------
# bookmark service
# ---------------------------------------------------------------------------

def bookmark_name(
    client: BeliClient, name: str, city: str | None = None, dry_run: bool = False
) -> dict:
    """Write a "Want to Try" bookmark with a confidence gate.

    Statuses: bookmarked | already_bookmarked | already_ranked |
              would_bookmark (dry_run) | ambiguous | no_results
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    city = (city or "").strip() or None

    user_uuid = _logged_in_uuid(client)

    bm_raw = client.api_with_reauth(f"/api/get-bookmark/?user={user_uuid}&category=RES")
    bookmarked_ids = {
        (it.get("business") or {}).get("id") if isinstance(it.get("business"), dict)
        else it.get("business_id", it.get("id"))
        for it in (results_of(bm_raw) or [])
        if isinstance(it, dict)
    } - {None}

    # A ranked place must never be re-bookmarked (Beli drops the bookmark once
    # a place is ranked). Best-effort: failure here must not block bookmarking.
    ranked_ids: set = set()
    try:
        rank_raw = client.api_with_reauth(f"/api/get-ranking/?user={user_uuid}&category=RES")
        ranked_ids = {
            (it.get("business") or {}).get("id") if isinstance(it.get("business"), dict)
            else it.get("business_id", it.get("id"))
            for it in (results_of(rank_raw) or [])
            if isinstance(it, dict)
        } - {None}
    except Exception:
        pass

    params = {"term": name, "user": user_uuid}
    if city:
        params["city"] = city
    search_raw = client.api_with_reauth("/api/search-app/?" + _urlencode(params))
    predictions = (
        search_raw.get("predictions") if isinstance(search_raw, dict) else None
    ) or []
    named = []
    for p in predictions:
        if not isinstance(p, dict):
            continue
        sf = p.get("structured_formatting") or {}
        nm = str(sf.get("main_text") or p.get("name") or "").strip()
        if not nm:
            continue
        named.append(
            {**p, "name": nm, "detail": str(sf.get("secondary_text") or "").strip() or None}
        )
    if not named:
        return {"status": "no_results", "name": name, "city": city}

    match = confident_match(name, named)
    if not match:
        return {
            "status": "ambiguous",
            "name": name,
            "city": city,
            "candidates": [
                {"name": p["name"], "detail": p["detail"]} for p in named[:5]
            ],
        }

    # Duplicate-record guard: Beli's DB can hold several records for the same
    # restaurant. If ANY confidently-matching prediction is already ranked or
    # bookmarked under any record, report that state instead of writing.
    def _confident(p):
        return confident_match(name, [p]) is not None

    dup_ranked = next(
        (p for p in named if isinstance(p.get("business"), int) and p["business"] in ranked_ids and _confident(p)),
        None,
    )
    dup_saved = next(
        (p for p in named if isinstance(p.get("business"), int) and p["business"] in bookmarked_ids and _confident(p)),
        None,
    )
    dup_status = "already_ranked" if dup_ranked else ("already_bookmarked" if dup_saved else None)

    pred = dup_ranked or dup_saved or match[0]
    biz_id = pred.get("business") if isinstance(pred.get("business"), int) else None
    biz_name, biz_neighborhood = pred.get("name"), None

    if biz_id is None and pred.get("place_id") and not dry_run:
        created = client.api_with_reauth(
            "/api/business/?place_id=" + urllib_parse_quote(str(pred["place_id"]))
        )
        c0 = results_of(created)
        full = ((c0[0] or {}).get("business") or c0[0]) if c0 else {}
        full = full if isinstance(full, dict) else {}
        biz_id = full.get("id")
        biz_name = full.get("name") or pred.get("name")
        biz_neighborhood = full.get("neighborhood")
    elif biz_id is not None:
        try:
            d = client.api_with_reauth(f"/api/business/?id={biz_id}")
            d0 = results_of(d)
            full = ((d0[0] or {}).get("business") or d0[0]) if d0 else {}
            if isinstance(full, dict) and full.get("id"):
                biz_name = full.get("name") or pred.get("name")
                biz_neighborhood = full.get("neighborhood")
        except Exception:
            pass

    business = {"id": biz_id, "name": biz_name, "neighborhood": biz_neighborhood}
    if dup_status:
        return {"status": dup_status, "name": name, "business": business}
    if dry_run:
        return {
            "status": "would_bookmark",
            "name": name,
            "business": business if biz_id else {
                "name": pred.get("name"),
                "detail": pred.get("detail"),
                "place_id": pred.get("place_id"),
            },
        }
    if not biz_id:
        raise ValueError("could not resolve a Beli business id")
    client.api_with_reauth(
        "/api/add-bookmark/", method="POST",
        body={"user_id": user_uuid, "business_id": biz_id},
    )
    return {"status": "bookmarked", "name": name, "business": business}


def _urlencode(params: dict) -> str:
    import urllib.parse as _up

    return _up.urlencode(params)


def urllib_parse_quote(s: str) -> str:
    import urllib.parse as _up

    return _up.quote(s, safe="")


# ---------------------------------------------------------------------------
# @beli_eats caption mining (beli_eats_watch.py)
# ---------------------------------------------------------------------------

CITY_HINTS = [
    (r"\bnyc\b|new york|manhattan|brooklyn|queens|bronx|staten island|east village|west village|soho|tribeca|chelsea|harlem|astoria|williamsburg", "New York, NY"),
    (r"\blos angeles\b|\bla\b|hollywood|santa monica|beverly hills|silver lake", "Los Angeles, CA"),
    (r"\bsan francisco\b|\bsf\b|mission district", "San Francisco, CA"),
    (r"\bchicago\b|wicker park|logan square", "Chicago, IL"),
    (r"\bmiami\b|wynwood|south beach", "Miami, FL"),
    (r"\bboston\b|cambridge|south end", "Boston, MA"),
    (r"\bwashington\b|\bdc\b|georgetown|adams morgan", "Washington, DC"),
    (r"\bphiladelphia\b|\bphilly\b", "Philadelphia, PA"),
    (r"\bseattle\b|capitol hill|ballard", "Seattle, WA"),
    (r"\baustin\b", "Austin, TX"),
    (r"\bsan juan\b|puerto rico", "San Juan, PR"),
    (r"\blondon\b|soho london|shoreditch", "London, UK"),
]


def guess_city(caption: str | None) -> str | None:
    text = (caption or "").lower()
    for pattern, city in CITY_HINTS:
        if re.search(pattern, text):
            return city
    return None


def candidates_from_caption(caption: str | None) -> list:
    """Extract restaurant-name candidates from an @beli_eats caption."""
    text = caption or ""
    cands: list = []
    # "📍 Table Mercato (East Village, Manhattan)"
    for m in re.finditer(r"📍\s*([^(\n@]{2,60}?)\s*\(", text):
        cands.append(m.group(1).strip())
    # numbered lists: "1. Lucali @lucali_bk"
    for m in re.finditer(r"(?:^|\n)\s*\d+[.)]\s*([A-Z][^@\n(]{1,50}?)(?=\s*(?:@|\n|$))", text):
        cands.append(m.group(1).strip())
    # @mentions -> name variants ("lucali_bk" -> "Lucali Bk", "Lucali")
    for handle in re.findall(r"@([\w.]+)", text):
        if handle.lower() in ("beli_eats",):
            continue
        base = handle.replace(".", " ").replace("_", " ").strip()
        if not base or len(base) < 3:
            continue
        cands.append(base.title())
        first_tok = base.split()[0]
        if len(first_tok) >= 4 and first_tok.lower() != base.lower():
            cands.append(first_tok.title())
    seen, out = set(), []
    for c in cands:
        c = re.sub(r"\s+", " ", c).strip(" -–—.,!?\"'")
        key = c.lower()
        if not c or len(c) < 3 or key in seen or key in _AMBIGUOUS_STOPWORDS:
            continue
        if len(c.split()) > 6:
            continue
        seen.add(key)
        out.append(c)
    return out
