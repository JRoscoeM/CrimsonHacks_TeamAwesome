"""SQLite cache of places, plus query helpers.

The database lives at ``<project>/data/places.db`` (gitignored); set the
``PLACES_DB_PATH`` environment variable to use a different file. It's filled by
``python -m outdoorsApp.places.seed``.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .model import Place

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "places.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    designation TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    image_url   TEXT NOT NULL DEFAULT '',
    images      TEXT NOT NULL DEFAULT '[]',
    park_code   TEXT NOT NULL DEFAULT '',
    activities  TEXT NOT NULL DEFAULT '[]',
    amenities   TEXT NOT NULL DEFAULT '[]',
    wheelchair  INTEGER,
    restrooms   INTEGER,
    reservable  INTEGER,
    raw         TEXT NOT NULL DEFAULT '{}',
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS places_kind ON places(kind);
CREATE INDEX IF NOT EXISTS places_source ON places(source);
CREATE INDEX IF NOT EXISTS places_lat_lon ON places(lat, lon);

-- Kept separate so re-seeding a source doesn't wipe matched Google IDs.
-- (Google's terms allow storing place IDs; don't store ratings/reviews here.)
CREATE TABLE IF NOT EXISTS google_ids (
    place_id        TEXT PRIMARY KEY,
    google_place_id TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Weather tables are keyed by place id and kept apart from places for the same reason.
-- Monthly averages for each place (index 0 = January), from a year of daily records.
CREATE TABLE IF NOT EXISTS climate (
    place_id     TEXT PRIMARY KEY,
    elevation_ft REAL,
    highs_f      TEXT NOT NULL,
    lows_f       TEXT NOT NULL,
    period       TEXT NOT NULL,
    source       TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- Latest forecast per place. days = [{date, high_f, low_f, code, precip_pct}], local dates.
CREATE TABLE IF NOT EXISTS forecasts (
    place_id       TEXT PRIMARY KEY,
    fetched_at     TEXT NOT NULL,
    local_time     TEXT NOT NULL,
    current_temp_f REAL,
    current_code   INTEGER,
    days           TEXT NOT NULL
);

-- NPS monthly recreation visitors per park code (index 0 = January), averaged over `period`.
CREATE TABLE IF NOT EXISTS visitation (
    park_code  TEXT PRIMARY KEY,
    monthly    TEXT NOT NULL,
    period     TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Road drive time from an origin (lat/lon rounded to 2 decimals, "40.76,-111.89") to a place.
CREATE TABLE IF NOT EXISTS drive_times (
    origin_key TEXT NOT NULL,
    place_id   TEXT NOT NULL,
    minutes    REAL NOT NULL,
    miles      REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (origin_key, place_id)
);

CREATE TABLE IF NOT EXISTS seed_runs (
    source      TEXT PRIMARY KEY,
    count       INTEGER NOT NULL,
    finished_at TEXT NOT NULL
);
"""

_COLUMNS = ("id", "source", "source_id", "name", "kind", "lat", "lon", "designation",
            "description", "url", "image_url", "images", "park_code", "activities", "amenities",
            "wheelchair", "restrooms", "reservable", "raw", "updated_at")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and create if needed) the places database."""
    path = Path(path or os.environ.get("PLACES_DB_PATH") or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a teammate's database was first created."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(places)")}
    if "images" not in existing:
        with conn:
            conn.execute("ALTER TABLE places ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")


def _bool_or_none(value) -> bool | None:
    return None if value is None else bool(value)


def _row_to_place(row: sqlite3.Row) -> Place:
    keys = row.keys()
    return Place(
        id=row["id"], source=row["source"], source_id=row["source_id"], name=row["name"],
        kind=row["kind"], lat=row["lat"], lon=row["lon"], designation=row["designation"],
        description=row["description"], url=row["url"], image_url=row["image_url"],
        images=json.loads(row["images"]), park_code=row["park_code"], activities=json.loads(row["activities"]),
        amenities=json.loads(row["amenities"]), wheelchair=_bool_or_none(row["wheelchair"]),
        restrooms=_bool_or_none(row["restrooms"]), reservable=_bool_or_none(row["reservable"]),
        google_place_id=row["google_place_id"] if "google_place_id" in keys else None,
        raw=json.loads(row["raw"]) if "raw" in keys else {},
    )


def _place_to_row(place: Place, now: str) -> tuple:
    def as_int(value):
        return None if value is None else int(value)

    return (place.id, place.source, place.source_id, place.name, place.kind, place.lat, place.lon,
            place.designation, place.description, place.url, place.image_url,
            json.dumps(place.images), place.park_code,
            json.dumps(place.activities), json.dumps(place.amenities), as_int(place.wheelchair),
            as_int(place.restrooms), as_int(place.reservable), json.dumps(place.raw), now)


# --- Writing -----------------------------------------------------------------

def replace_source(conn: sqlite3.Connection, source: str, places: Iterable[Place]) -> int:
    """Swap out every place from ``source`` with ``places``, in one transaction."""
    now = _now()
    rows = {p.id: _place_to_row(p, now) for p in places}  # dict drops duplicate ids
    with conn:
        conn.execute("DELETE FROM places WHERE source = ?", (source,))
        conn.executemany(
            f"INSERT INTO places ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
            rows.values(),
        )
        conn.execute(
            "INSERT INTO seed_runs (source, count, finished_at) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET count = excluded.count, finished_at = excluded.finished_at",
            (source, len(rows), now),
        )
    return len(rows)


def set_google_place_id(place_id: str, google_place_id: str, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or connect()
    with conn:
        conn.execute(
            "INSERT INTO google_ids (place_id, google_place_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(place_id) DO UPDATE SET google_place_id = excluded.google_place_id, "
            "updated_at = excluded.updated_at",
            (place_id, google_place_id, _now()),
        )


# --- Reading -----------------------------------------------------------------

_SELECT = ("SELECT p.{cols}, g.google_place_id FROM places p "
           "LEFT JOIN google_ids g ON g.place_id = p.id")


def get_place(place_id: str, conn: sqlite3.Connection | None = None) -> Place | None:
    """One place by id (e.g. ``"nps:zion"``), including its raw API record."""
    conn = conn or connect()
    row = conn.execute(_SELECT.format(cols=", p.".join(_COLUMNS)) + " WHERE p.id = ?",
                       (place_id,)).fetchone()
    return _row_to_place(row) if row else None


def find_places(
    *,
    kind: str | Iterable[str] | None = None,
    activities: Iterable[str] = (),
    text: str | None = None,
    near: tuple[float, float] | None = None,
    within_mi: float | None = None,
    wheelchair: bool | None = None,
    restrooms: bool | None = None,
    source: str | Iterable[str] | None = None,
    limit: int | None = 50,
    include_raw: bool = False,
    conn: sqlite3.Connection | None = None,
) -> list[Place]:
    """Search the cache. Every argument is optional and they combine with AND.

    kind        one kind or several, e.g. ``Kind.CAMPGROUND`` or ``["national_park", "state_park"]``
    activities  places must have *all* of these canonical tags, e.g. ``["hiking", "camping"]``
    text        substring match on name or description
    near        ``(lat, lon)``: results get ``distance_mi`` and are sorted nearest first
    within_mi   with ``near``: drop anything farther than this (straight-line miles)
    wheelchair / restrooms   ``True`` = only places known to have it
    limit       max results (``None`` for all)

    include_raw also load each place's raw API record (slower; off by default)
    """
    conn = conn or connect()
    where, params = [], []

    def add_in(column: str, value) -> None:
        values = [value] if isinstance(value, str) else list(value)
        where.append(f"p.{column} IN ({', '.join('?' * len(values))})")
        params.extend(values)

    if kind:
        add_in("kind", kind)
    if source:
        add_in("source", source)
    for tag in activities:
        where.append("EXISTS (SELECT 1 FROM json_each(p.activities) WHERE value = ?)")
        params.append(tag)
    if text:
        where.append("(p.name LIKE ? OR p.description LIKE ?)")
        params += [f"%{text}%"] * 2
    if wheelchair is not None:
        where.append("p.wheelchair = ?")
        params.append(int(wheelchair))
    if restrooms is not None:
        where.append("p.restrooms = ?")
        params.append(int(restrooms))
    if near and within_mi:  # cheap bounding-box prefilter; exact distance below
        lat, lon = near
        dlat = within_mi / 69.0
        dlon = within_mi / (69.0 * max(math.cos(math.radians(lat)), 0.01))
        where.append("p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?")
        params += [lat - dlat, lat + dlat, lon - dlon, lon + dlon]

    cols = [c for c in _COLUMNS if include_raw or c != "raw"]
    sql = _SELECT.format(cols=", p.".join(cols))
    if where:
        sql += " WHERE " + " AND ".join(where)
    if not near:
        sql += " ORDER BY p.name"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

    places = [_row_to_place(row) for row in conn.execute(sql, params)]
    if near:
        for place in places:
            place.distance_mi = round(place.distance_to(*near), 1)
        if within_mi:
            places = [p for p in places if p.distance_mi <= within_mi]
        places.sort(key=lambda p: p.distance_mi)
        if limit is not None:
            places = places[:limit]
    return places


# --- Weather -----------------------------------------------------------------

def save_climate(conn: sqlite3.Connection, rows: dict[str, dict]) -> None:
    """rows: {place_id: {elevation_ft, highs_f[12], lows_f[12], period, source}}"""
    now = _now()
    with conn:
        conn.executemany(
            "INSERT INTO climate (place_id, elevation_ft, highs_f, lows_f, period, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(place_id) DO UPDATE SET "
            "elevation_ft = excluded.elevation_ft, highs_f = excluded.highs_f, lows_f = excluded.lows_f, "
            "period = excluded.period, source = excluded.source, updated_at = excluded.updated_at",
            [(pid, r.get("elevation_ft"), json.dumps(r["highs_f"]), json.dumps(r["lows_f"]),
              r["period"], r["source"], now) for pid, r in rows.items()],
        )


def load_climate(conn: sqlite3.Connection | None = None) -> dict[str, dict]:
    conn = conn or connect()
    return {
        row["place_id"]: {"elevation_ft": row["elevation_ft"], "highs_f": json.loads(row["highs_f"]),
                          "lows_f": json.loads(row["lows_f"]), "period": row["period"], "source": row["source"]}
        for row in conn.execute("SELECT * FROM climate")
    }


def save_forecasts(conn: sqlite3.Connection, rows: dict[str, dict]) -> None:
    """rows: {place_id: {local_time, current_temp_f, current_code, days[...]}}"""
    now = _now()
    with conn:
        conn.executemany(
            "INSERT INTO forecasts (place_id, fetched_at, local_time, current_temp_f, current_code, days) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(place_id) DO UPDATE SET "
            "fetched_at = excluded.fetched_at, local_time = excluded.local_time, "
            "current_temp_f = excluded.current_temp_f, current_code = excluded.current_code, days = excluded.days",
            [(pid, now, r["local_time"], r.get("current_temp_f"), r.get("current_code"), json.dumps(r["days"]))
             for pid, r in rows.items()],
        )


def load_forecasts(conn: sqlite3.Connection | None = None) -> dict[str, dict]:
    conn = conn or connect()
    return {
        row["place_id"]: {"fetched_at": row["fetched_at"], "local_time": row["local_time"],
                          "current_temp_f": row["current_temp_f"], "current_code": row["current_code"],
                          "days": json.loads(row["days"])}
        for row in conn.execute("SELECT * FROM forecasts")
    }


def oldest_forecast(conn: sqlite3.Connection | None = None) -> datetime | None:
    """When the stalest forecast was fetched (None if any place has no forecast)."""
    conn = conn or connect()
    missing = conn.execute(
        "SELECT COUNT(*) FROM places p LEFT JOIN forecasts f ON f.place_id = p.id WHERE f.place_id IS NULL"
    ).fetchone()[0]
    oldest = conn.execute("SELECT MIN(fetched_at) FROM forecasts").fetchone()[0]
    if missing or not oldest:
        return None
    return datetime.fromisoformat(oldest)


# --- Visitation and drive times ----------------------------------------------

def save_visitation(conn: sqlite3.Connection, rows: dict[str, list[float]], period: str) -> None:
    now = _now()
    with conn:
        conn.executemany(
            "INSERT INTO visitation (park_code, monthly, period, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(park_code) DO UPDATE SET monthly = excluded.monthly, period = excluded.period, "
            "updated_at = excluded.updated_at",
            [(code.lower(), json.dumps(monthly), period, now) for code, monthly in rows.items()],
        )


def load_visitation(conn: sqlite3.Connection | None = None) -> dict[str, dict]:
    conn = conn or connect()
    return {row["park_code"]: {"monthly": json.loads(row["monthly"]), "period": row["period"]}
            for row in conn.execute("SELECT * FROM visitation")}


def save_drive_times(conn: sqlite3.Connection, origin_key: str, rows: dict[str, tuple[float, float]]) -> None:
    """rows: {place_id: (minutes, miles)}"""
    now = _now()
    with conn:
        conn.executemany(
            "INSERT INTO drive_times (origin_key, place_id, minutes, miles, fetched_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(origin_key, place_id) DO UPDATE SET minutes = excluded.minutes, "
            "miles = excluded.miles, fetched_at = excluded.fetched_at",
            [(origin_key, pid, minutes, miles, now) for pid, (minutes, miles) in rows.items()],
        )


def load_drive_times(conn: sqlite3.Connection, origin_key: str) -> dict[str, tuple[float, float]]:
    return {row["place_id"]: (row["minutes"], row["miles"]) for row in conn.execute(
        "SELECT place_id, minutes, miles FROM drive_times WHERE origin_key = ?", (origin_key,))}


def stats(conn: sqlite3.Connection | None = None) -> dict:
    """Counts by kind and source, plus when each source was last seeded."""
    conn = conn or connect()
    return {
        "total": conn.execute("SELECT COUNT(*) FROM places").fetchone()[0],
        "by_kind": dict(conn.execute("SELECT kind, COUNT(*) FROM places GROUP BY kind ORDER BY 2 DESC")),
        "by_source": dict(conn.execute("SELECT source, COUNT(*) FROM places GROUP BY source")),
        "seeded_at": dict(conn.execute("SELECT source, finished_at FROM seed_runs")),
    }
