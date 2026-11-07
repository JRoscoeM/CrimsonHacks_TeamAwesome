"""Road drive times from an origin to every cached place, via OSRM.

OSRM (https://project-osrm.org) routes over OpenStreetMap roads. The public demo
server needs no key and its results may be stored, but it asks for light use
(about one request a second, at most 100 coordinates per request), so drive
times are saved per origin and only fetched once. Origins are rounded to
2 decimal places (~1 km), so "Near me" from the same spot reuses saved times.
"""

from __future__ import annotations

import sqlite3
import time

from .http import request_json
from .store import connect, find_places, load_drive_times, save_drive_times

OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving/"
MAX_DESTINATIONS = 99  # + 1 origin = OSRM demo server's 100-coordinate limit
METERS_PER_MILE = 1609.344
# The demo server's default car speeds are conservative: on Utah highway trips its times
# came out ~20-25% longer than typical (e.g. SLC to Arches 4h53 vs ~3h50, to Zion 5h20 vs
# ~4h20) while its distances matched. Saved times are raw OSRM; this scales them for display.
DURATION_FACTOR = 0.8


def origin_key(lat: float, lon: float) -> str:
    return f"{lat:.2f},{lon:.2f}"


def fetch_drive_times(lat: float, lon: float, places) -> dict[str, tuple[float, float]]:
    """{place_id: (minutes, miles)} by road. Places OSRM can't route to are left out."""
    results = {}
    for i in range(0, len(places), MAX_DESTINATIONS):
        batch = places[i:i + MAX_DESTINATIONS]
        coords = ";".join([f"{lon:.5f},{lat:.5f}", *(f"{p.lon:.5f},{p.lat:.5f}" for p in batch)])
        response = request_json(OSRM_TABLE_URL + coords,
                                params={"sources": "0", "annotations": "duration,distance"}, timeout=60)
        durations, distances = response["durations"][0][1:], response["distances"][0][1:]
        for place, seconds, meters in zip(batch, durations, distances):
            if seconds is not None and meters is not None:
                results[place.id] = (seconds / 60, meters / METERS_PER_MILE)
        if i + MAX_DESTINATIONS < len(places):
            time.sleep(1.1)
    return results


def ensure_drive_times(lat: float, lon: float, conn: sqlite3.Connection | None = None) -> dict[str, tuple[float, float]]:
    """Saved drive times from this origin, downloading any places that are missing."""
    conn = conn or connect()
    key = origin_key(lat, lon)
    saved = load_drive_times(conn, key)
    missing = [p for p in find_places(limit=None, conn=conn) if p.id not in saved]
    if missing:
        fetched = fetch_drive_times(lat, lon, missing)
        save_drive_times(conn, key, fetched)
        saved.update(fetched)
    return saved
