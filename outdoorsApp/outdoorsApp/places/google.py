"""Google Places: match places to Google IDs, and look up ratings and reviews.

**Every call here can be billed, so nothing runs by default.** The app only
calls Google when the ``GOOGLE_RATINGS`` env var is "details" or "all", and the
seed's ``google_ids`` step only runs with ``--allow-billed``.

Google's terms allow storing place IDs, but not ratings or reviews. So:

* ``match_place_ids()`` (seed step ``google_ids``) finds each cached place's
  Google place ID once with Text Search and saves it in the database.
* ``place_details()`` looks up rating, review count and reviews for one place
  when the app needs them, and keeps the result **in memory only** (for up to
  24 hours, never written to disk). Each lookup is a billed Place Details call,
  so a per-process budget caps how many the app can make.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

from .. import keys
from .http import SourceError, request_json
from .model import Place, haversine_mi
from .store import connect, find_places, set_google_place_id

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/"
DETAILS_TTL_S = 24 * 3600
DETAILS_BUDGET = int(os.environ.get("GOOGLE_DETAILS_BUDGET", "200"))  # billed lookups per app run
# Second guard so nothing can call Google by accident: off unless explicitly enabled.
RATINGS_ENABLED = os.environ.get("GOOGLE_RATINGS", "off").lower() in ("details", "all")

_GENERIC = {"the", "national", "state", "park", "monument", "resort", "mountain", "ski", "area",
            "campground", "camp", "group", "site", "recreation", "historic", "historical", "and", "of", "rv"}


def _words(name: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if w not in _GENERIC and len(w) > 2}


def _headers(field_mask: str) -> dict:
    return {"X-Goog-Api-Key": keys.GOOGLE_MAPS_API_KEY or "", "X-Goog-FieldMask": field_mask,
            "Content-Type": "application/json"}


# --- One-time ID matching ----------------------------------------------------

def find_google_id(place: Place) -> str | None:
    """Best Google match near the place whose name shares a meaningful word with ours."""
    body = json.dumps({
        "textQuery": f"{place.name}, Utah",
        "locationBias": {"circle": {"center": {"latitude": place.lat, "longitude": place.lon}, "radius": 20000.0}},
        "pageSize": 3,
    }).encode()
    response = request_json(TEXT_SEARCH_URL, data=body,
                            headers=_headers("places.id,places.displayName,places.location"), timeout=30)
    max_mi = 15 if place.kind in ("national_park", "national_monument", "recreation_area", "state_park") else 3
    ours = _words(place.name)
    for candidate in response.get("places", []):
        loc = candidate.get("location") or {}
        name = (candidate.get("displayName") or {}).get("text", "")
        if not loc or haversine_mi(place.lat, place.lon, loc["latitude"], loc["longitude"]) > max_mi:
            continue
        if ours and not ours & _words(name):
            continue
        return candidate["id"]
    return None


def match_place_ids(conn: sqlite3.Connection | None = None, progress=print,
                    allow_billed: bool = False) -> tuple[int, int]:
    """Find Google IDs for places that don't have one. Returns (matched, tried).

    Text Search calls are billed past Google's free monthly allowance, so this
    refuses to run unless ``allow_billed`` is True.
    """
    if not allow_billed:
        raise SourceError("refusing to call Google without --allow-billed (Text Search can be billed)")
    if not keys.GOOGLE_MAPS_API_KEY:
        raise SourceError("GOOGLE_MAPS_API_KEY isn't set in .env")
    conn = conn or connect()
    todo = [p for p in find_places(limit=None, conn=conn) if not p.google_place_id]
    matched = 0
    for i, place in enumerate(todo, 1):
        google_id = find_google_id(place)
        if google_id:
            set_google_place_id(place.id, google_id, conn=conn)
            matched += 1
        if i % 25 == 0:
            progress(f"{i}/{len(todo)} looked up, {matched} matched")
        time.sleep(0.7)  # stay under the project's per-minute quota (it returned 429 at ~10/s)
    return matched, len(todo)


# --- Ratings and reviews (in memory only) ------------------------------------

_details: dict[str, tuple[float, dict]] = {}  # google id -> (fetched at, details)
_lock = threading.Lock()
_used = 0


def cached_details(google_id: str) -> dict | None:
    hit = _details.get(google_id)
    return hit[1] if hit and time.time() - hit[0] < DETAILS_TTL_S else None


def place_details(google_id: str) -> dict | None:
    """{rating, count, maps_url, reviews: [{author, stars, text, when}]} or None.

    Returns the in-memory copy if it's fresh. Otherwise makes one billed call,
    unless the per-run budget is used up.
    """
    global _used
    if not RATINGS_ENABLED or not keys.GOOGLE_MAPS_API_KEY or not google_id:
        return None
    hit = cached_details(google_id)
    if hit is not None:
        return hit
    with _lock:
        if _used >= DETAILS_BUDGET:
            return None
        _used += 1
    try:
        # "reviews" isn't requested: Google returned none for this project's key in testing, and
        # asking for it bills every lookup at the pricier Atmosphere rate. Add it back here if needed.
        data = request_json(DETAILS_URL + google_id,
                            headers=_headers("rating,userRatingCount,googleMapsUri"), timeout=20)
    except SourceError:
        return None
    details = {
        "rating": data.get("rating"), "count": data.get("userRatingCount") or 0,
        "maps_url": data.get("googleMapsUri", ""),
        "reviews": [
            {"author": (r.get("authorAttribution") or {}).get("displayName", "Google user"),
             "stars": int(r.get("rating") or 0), "text": (r.get("text") or {}).get("text", ""),
             "when": r.get("relativePublishTimeDescription", "")}
            for r in data.get("reviews", [])[:3] if (r.get("text") or {}).get("text")
        ],
    }
    _details[google_id] = (time.time(), details)
    return details


def budget_left() -> int:
    return max(0, DETAILS_BUDGET - _used)
