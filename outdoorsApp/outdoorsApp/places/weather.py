"""Weather for cached places, from Open-Meteo (free, no key, results may be stored).

Two kinds of data, both saved in the places database:

* **Forecasts**: current conditions plus 16 days of daily highs and lows, for
  every place in one or two requests. ``refresh_forecasts()`` only downloads
  when the saved ones are older than ``max_age_minutes``; the app calls it on
  page load.
* **Climate**: each place's elevation and its average high and low for every
  month, from a year of daily records. It doesn't change, so
  ``update_climate()`` only fetches places that don't have it yet. Open-Meteo
  weights a year of history heavily against its free limits, so this step is
  paced and takes a few minutes the first time.

Dates and times are local to Utah (America/Denver).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone

from .http import request_json
from .model import Place
from .store import (connect, find_places, load_climate, oldest_forecast, save_climate,
                    save_forecasts)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
TIMEZONE = "America/Denver"
CLIMATE_YEAR = 2025  # last full year of records
FORECAST_DAYS = 16

# WMO weather codes used by Open-Meteo.
_CODES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorms", 96: "Thunderstorms with hail", 99: "Thunderstorms with hail",
}


def describe(code: int | None) -> str:
    return _CODES.get(code, "") if code is not None else ""


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _coords(places: list[Place]) -> dict:
    return {"latitude": ",".join(f"{p.lat:.4f}" for p in places),
            "longitude": ",".join(f"{p.lon:.4f}" for p in places)}


def _as_list(response) -> list[dict]:
    """Open-Meteo returns one object for one location and a list for several."""
    return response if isinstance(response, list) else [response]


# --- Forecasts ---------------------------------------------------------------

def fetch_forecasts(places: list[Place]) -> dict[str, dict]:
    results = {}
    for batch in _batches(places, 50):
        response = request_json(FORECAST_URL, params={
            **_coords(batch),
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
            "current": "temperature_2m,weather_code",
            "temperature_unit": "fahrenheit", "timezone": TIMEZONE, "forecast_days": FORECAST_DAYS,
        }, timeout=60)
        for place, data in zip(batch, _as_list(response)):
            daily, current = data["daily"], data.get("current") or {}
            results[place.id] = {
                "local_time": current.get("time", ""),
                "current_temp_f": current.get("temperature_2m"),
                "current_code": current.get("weather_code"),
                "days": [
                    {"date": day, "high_f": high, "low_f": low, "code": code, "precip_pct": rain}
                    for day, high, low, code, rain in zip(
                        daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"],
                        daily["weather_code"], daily["precipitation_probability_max"])
                    if high is not None and low is not None
                ],
            }
    return results


def refresh_forecasts(conn: sqlite3.Connection | None = None, max_age_minutes: float = 60) -> int:
    """Re-download every place's forecast if the saved ones are too old. Returns places updated."""
    conn = conn or connect()
    oldest = oldest_forecast(conn)
    if oldest and (datetime.now(timezone.utc) - oldest).total_seconds() < max_age_minutes * 60:
        return 0
    places = find_places(limit=None, conn=conn)
    if not places:
        return 0
    forecasts = fetch_forecasts(places)
    save_forecasts(conn, forecasts)
    return len(forecasts)


# --- Climate -----------------------------------------------------------------

def fetch_elevations_ft(places: list[Place]) -> dict[str, float]:
    result = {}
    for batch in _batches(places, 100):
        response = request_json(ELEVATION_URL, params=_coords(batch), timeout=60)
        for place, meters in zip(batch, response.get("elevation", [])):
            if meters is not None:
                result[place.id] = round(meters * 3.28084)
    return result


def _monthly_means(dates: list[str], values: list[float | None]) -> list[int]:
    sums, counts = [0.0] * 12, [0] * 12
    for day, value in zip(dates, values):
        if value is not None:
            month = int(day[5:7]) - 1
            sums[month] += value
            counts[month] += 1
    return [round(s / c) if c else None for s, c in zip(sums, counts)]


def fetch_monthly_climate(places: list[Place], progress: Callable[[str], None] = print,
                          batch_size: int = 10, pause_s: float = 35) -> dict[str, dict]:
    """Average high/low per month from CLIMATE_YEAR's daily records.

    A year of one variable counts as ~26 calls against Open-Meteo's free limit of 600 a
    minute, so batches of 10 places are spaced ``pause_s`` apart.
    """
    results = {}
    batches = list(_batches(places, batch_size))
    for i, batch in enumerate(batches, 1):
        response = request_json(ARCHIVE_URL, params={
            **_coords(batch),
            "start_date": f"{CLIMATE_YEAR}-01-01", "end_date": f"{CLIMATE_YEAR}-12-31",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": "fahrenheit", "timezone": TIMEZONE,
        }, timeout=120)
        for place, data in zip(batch, _as_list(response)):
            daily = data["daily"]
            highs = _monthly_means(daily["time"], daily["temperature_2m_max"])
            lows = _monthly_means(daily["time"], daily["temperature_2m_min"])
            if None not in highs and None not in lows:
                results[place.id] = {"highs_f": highs, "lows_f": lows}
        progress(f"{i}/{len(batches)} batches")
        if i < len(batches):
            time.sleep(pause_s)
    return results


def update_climate(conn: sqlite3.Connection | None = None, progress: Callable[[str], None] = print) -> int:
    """Fetch elevation + monthly averages for places that don't have them yet."""
    conn = conn or connect()
    have = load_climate(conn)
    missing = [p for p in find_places(limit=None, conn=conn) if p.id not in have]
    if not missing:
        return 0
    elevations = fetch_elevations_ft(missing)
    monthly = fetch_monthly_climate(missing, progress=progress)
    rows = {
        pid: {**values, "elevation_ft": elevations.get(pid), "period": str(CLIMATE_YEAR),
              "source": "Open-Meteo historical weather"}
        for pid, values in monthly.items()
    }
    save_climate(conn, rows)
    return len(rows)
