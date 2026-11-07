"""Turn a typed address or place name into coordinates, via Nominatim (OpenStreetMap).

Free, no key, no billing. The public server's usage policy asks for at most one
request a second, an identifying User-Agent, and no search-as-you-type, so the
app only geocodes when the user presses Enter or leaves the field, and every
result (including "not found") is saved in the places database so each query is
looked up once.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from datetime import datetime, timezone

from .http import SourceError, request_json
from .store import connect

SEARCH_URL = "https://nominatim.openstreetmap.org/search"
# Prefer results in and around Utah, but still allow anywhere in the US.
UTAH_VIEWBOX = "-114.6,42.6,-108.4,36.4"  # left, top, right, bottom

_STATE_ABBR = {"Utah": "UT", "Nevada": "NV", "Arizona": "AZ", "Colorado": "CO", "Idaho": "ID",
               "Wyoming": "WY", "New Mexico": "NM", "California": "CA"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS geocodes (
    query      TEXT PRIMARY KEY,
    lat        REAL,
    lon        REAL,
    label      TEXT,
    fetched_at TEXT NOT NULL
);
"""

_lock = threading.Lock()
_last_request = 0.0


def _normalize(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _label(result: dict) -> str:
    """Short label like "123 Main St, Moab, UT" or "Provo, UT"."""
    address = result.get("address") or {}
    town = next((address[k] for k in ("city", "town", "village", "hamlet", "suburb") if address.get(k)), "")
    state = address.get("state", "")
    state = _STATE_ABBR.get(state, state)
    street = " ".join(x for x in (address.get("house_number"), address.get("road")) if x)
    name = result.get("name") or ""
    # A named place (a landmark, park or road) reads better by name; plain addresses by street.
    first = name if name and name != town else street
    parts = [p for p in (first, town or address.get("county", ""), state) if p]
    return ", ".join(dict.fromkeys(parts)) or result.get("display_name", "")


def _search(query: str) -> dict | None:
    global _last_request
    with _lock:  # one request a second, across all users of this app process
        wait = 1.1 - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        results = request_json(SEARCH_URL, params={
            "q": query, "format": "jsonv2", "addressdetails": 1, "limit": 1,
            "countrycodes": "us", "viewbox": UTAH_VIEWBOX, "bounded": 0,
        }, headers={"Accept-Language": "en"}, timeout=20)
    if not results:
        return None
    best = results[0]
    return {"lat": float(best["lat"]), "lon": float(best["lon"]), "label": _label(best)}


def geocode(query: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """{lat, lon, label} for the query, or None if nothing matched.

    Raises SourceError if Nominatim can't be reached (nothing is saved then).
    """
    key = _normalize(query)
    if len(key) < 2:
        return None
    conn = conn or connect()
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT lat, lon, label FROM geocodes WHERE query = ?", (key,)).fetchone()
    if row is not None:
        return None if row[0] is None else {"lat": row[0], "lon": row[1], "label": row[2]}
    found = _search(query)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO geocodes (query, lat, lon, label, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (key, found and found["lat"], found and found["lon"], found and found["label"],
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    return found


__all__ = ["SourceError", "geocode"]
