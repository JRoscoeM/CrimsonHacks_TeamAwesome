"""Place data for the UI, plus date-aware presentation helpers.

``PLACES`` = the curated samples in ``sample_places.json`` + every other place in
the places cache (``data/places.db``, filled by ``python -m outdoorsApp.places.seed``),
converted to the same shape. Curated places keep their hand-written details and
borrow the cache's real photo and website. Cache-only places get honest
defaults, and their seasonal scores, crowds and temperatures are estimated
from the nearest similar curated place (see ``EstimateNote``).

Set ``WAYFINDER_SAMPLE_ONLY=1`` to use only the curated samples (the tests do).
The cache is read once at startup, so restart the app after re-seeding.
"""

import calendar
import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


SAMPLE_PLACES = json.loads(Path(__file__).with_name("sample_places.json").read_text(encoding="utf-8"))
MONTHS = list(calendar.month_abbr)[1:]
LANDSCAPES = {"adaptive-recreation", "campground", "national-monument", "national-park",
              "scenic-area", "ski-resort", "state-park"}


def landscape(place_type: str) -> str:
    """Fallback artwork for a place type (assets/landscapes/*.svg)."""
    slug = place_type.lower().replace(" ", "-")
    return f"/landscapes/{slug if slug in LANDSCAPES else 'scenic-area'}.svg"


# --- Merging the places cache -----------------------------------------------

# Cache activity tags -> the activity names the UI filters on.
_ACTIVITY_NAMES = {
    "hiking": "Hiking", "camping": "Camping", "skiing": "Skiing", "biking": "Biking",
    "boating": "Water", "swimming": "Water", "fishing": "Water", "scenic_drive": "Scenic Drive",
    "wildlife": "Wildlife", "stargazing": "Stargazing", "climbing": "Climbing",
    "horseback": "Horseback riding", "off_road": "Off-road",
}
_GENERIC_WORDS = {"the", "national", "state", "park", "monument", "resort", "mountain", "ski",
                  "area", "campground", "historical", "historic", "site", "recreation"}


def _miles(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(min(1, a)))


def _name_words(name: str) -> list[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return [w for w in words if w not in _GENERIC_WORDS]


def _name_key(name: str) -> str:
    words = _name_words(name)
    return words[0] if words else ""


def _sample_distance(sample: dict, place) -> float:
    return _miles(sample["FacilityLatitude"], sample["FacilityLongitude"], place.lat, place.lon)


def _matching_sample(place, samples: list[dict]) -> dict | None:
    """The curated sample describing the same place, within 30 mi: same type and a similar
    name, or the same full name even if the sources disagree on type (e.g. Bonneville
    Salt Flats is a "Scenic Area" in the samples but a state park in OpenStreetMap)."""
    key, words = _name_key(place.name), _name_words(place.name)
    for sample in samples:
        if not key or _sample_distance(sample, place) > 30:
            continue
        same_type = sample["Type"] == place.kind_label and _name_key(sample["FacilityName"]) == key
        # A campground inside a park is its own place, even with the park's name.
        either_campground = "Campground" in (sample["Type"], place.kind_label)
        if same_type or (not either_campground and _name_words(sample["FacilityName"]) == words):
            return sample
    return None


def _reference_sample(place, place_type: str, samples: list[dict]) -> dict:
    """Nearest curated place to borrow seasonal estimates from."""
    same = [s for s in samples if s["Type"] == place_type]
    if same:
        nearest = min(same, key=lambda s: _sample_distance(s, place))
        if _sample_distance(nearest, place) <= 100:
            return nearest
    # Never borrow a ski resort's winter-heavy season for a non-ski place.
    pool = [s for s in samples if (s["Type"] == "Ski Resort") == (place_type == "Ski Resort")] or samples
    return min(pool, key=lambda s: _sample_distance(s, place))


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fee(fees) -> tuple[str, int] | None:
    """NPS fee list -> (display text, cost tier 0/1/2)."""
    priced = [(_to_float(f.get("cost")), (f.get("title") or "").strip()) for f in fees or []]
    priced = [(cost, title) for cost, title in priced if cost is not None]
    if not priced:
        return None
    if all(cost == 0 for cost, _ in priced):
        return "Free", 0
    cost, title = next((c, t) for c, t in priced if c > 0)
    label = title.rsplit(" - ", 1)[-1] if " - " in title else title
    return f"${cost:g}" + (f" · {label}" if label else ""), 1 if cost < 20 else 2


def _humanize(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", key).capitalize()


def _cache_facts(place) -> dict:
    """Factual fields from the raw API record: cost, hours, phone, campsites, amenities."""
    raw = place.raw or {}
    facts = {"Hours": "", "Phone": "", "Campsites": "", "AmenitiesText": ""}
    if place.source in ("nps", "nps_campgrounds"):
        fee = _fee(raw.get("entranceFees") if place.source == "nps" else raw.get("fees"))
        if fee:
            facts["Cost"], facts["CostTier"] = fee
        hours = (raw.get("operatingHours") or [{}])[0].get("description", "")
        facts["Hours"] = hours if len(hours) <= 220 else hours[:217].rsplit(" ", 1)[0] + "…"
        phones = (raw.get("contacts") or {}).get("phoneNumbers") or []
        facts["Phone"] = next((p.get("phoneNumber", "") for p in phones if p.get("type") == "Voice"), "")
        sites = (raw.get("campsites") or {}).get("totalSites")
        if sites and str(sites) != "0":
            facts["Campsites"] = f"{sites} sites"
    elif place.source == "ridb":
        facts["Phone"] = raw.get("FacilityPhone") or ""
        if raw.get("FacilityUseFeeDescription"):
            facts["Cost"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw["FacilityUseFeeDescription"])).strip()[:120]
    elif place.source == "osm":
        tags = raw.get("tags") or {}
        facts["Phone"] = tags.get("phone") or tags.get("contact:phone", "")
    facts["AmenitiesText"] = ", ".join(_humanize(a) for a in place.amenities)
    return facts


def _from_cache(place, samples: list[dict], climate: dict | None) -> dict:
    place_type = place.kind_label
    ref = _reference_sample(place, place_type, samples)
    image = place.images[0] if place.images else {}
    reservable = place.kind == "campground" and bool(place.reservable)
    if climate:
        highs, elevation_ft = list(climate["highs_f"]), climate.get("elevation_ft")
        note = (f"Average temperatures come from {climate['period']} weather records for this spot. "
                f"Seasonal scores and crowds are estimated from {ref['FacilityName']}, the closest "
                "similar place we have detailed data for.")
    else:
        highs, elevation_ft = list(ref["HighsF"]), None
        note = (f"Seasonal scores, crowds and temperatures are estimated from {ref['FacilityName']}, "
                "the closest similar place we have detailed data for.")
    return {
        "FacilityID": place.id, "FacilityName": place.name, "Type": place_type,
        "FacilityDescription": place.description or f"{place_type} in Utah.",
        "FacilityLatitude": place.lat, "FacilityLongitude": place.lon,
        "ElevationFt": round(elevation_ft) if elevation_ft is not None else None,
        "Activities": list(dict.fromkeys(_ACTIVITY_NAMES[t] for t in place.activities if t in _ACTIVITY_NAMES)),
        "Rating": 0.0, "Reviews": 0,  # filled in once Google Places is connected
        "Cost": "Check with the site", "CostTier": None,
        "Reservation": reservable,
        "ReservationNote": "Campsites can be reserved on Recreation.gov." if reservable else "",
        "Season": list(ref["Season"]), "Crowds": list(ref["Crowds"]), "HighsF": highs,
        "EstimateNote": note,
        "Access": {"wheelchair": place.wheelchair is True, "stroller": False, "paved": False,
                   "restrooms": place.restrooms is True, "quiet": False, "shade": False, "medical": False},
        "AccessDetails": "We don't have detailed accessibility information for this place yet. "
                         "Check with the site before you go.",
        "QuietTime": "Not listed yet. Weekday mornings are usually quieter.",
        "Tip": "Services can be far apart in Utah. Fill up on gas and water before you head out.",
        "DogFriendly": False, "FamilyFriendly": False,
        "ThingsToDo": [], "UserReviews": [],
        "Image": place.image_url, "ImageCredit": image.get("credit", ""), "Url": place.url,
        "Source": place.source,
        **_cache_facts(place),
    }


def _db_path() -> Path | None:
    if os.environ.get("WAYFINDER_SAMPLE_ONLY"):
        return None
    from .places.store import DEFAULT_DB_PATH

    path = Path(os.environ.get("PLACES_DB_PATH") or DEFAULT_DB_PATH)
    return path if path.is_file() else None


# FacilityID -> cache place id, for places whose weather comes from the cache.
_FORECAST_SOURCE: dict[str, str] = {}
# FacilityID -> latest forecast {local_time, current_temp_f, current_code, days[...]}
FORECASTS: dict[str, dict] = {}


def _with_cache(samples: list[dict]) -> list[dict]:
    db_path = _db_path()
    if db_path is None:
        return samples
    from .places import connect, find_places
    from .places.store import load_climate

    try:
        conn = connect(db_path)
        try:
            cached = find_places(limit=None, include_raw=True, conn=conn)
            climate = load_climate(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return samples

    samples = [dict(s) for s in samples]
    extra = []
    for place in cached:
        match = _matching_sample(place, samples)
        if match is None:
            extra.append(_from_cache(place, samples, climate.get(place.id)))
            _FORECAST_SOURCE[place.id] = place.id
            continue
        # Same place as a curated sample: keep its hand-written details (including its
        # temperatures, which describe the area people visit rather than the park's center
        # point), and add the real photo, website, live forecast and contact facts.
        _FORECAST_SOURCE.setdefault(match["FacilityID"], place.id)
        if place.image_url and not match.get("Image"):
            match["Image"] = place.image_url
            match["ImageCredit"] = (place.images[0] if place.images else {}).get("credit", "")
        if place.url and not match.get("Url"):
            match["Url"] = place.url
        for key, value in _cache_facts(place).items():
            if key not in ("Cost", "CostTier") and value and not match.get(key):
                match[key] = value
    return samples + extra


def reload_forecasts() -> None:
    """Re-read saved forecasts from the cache into FORECASTS."""
    db_path = _db_path()
    if db_path is None or not _FORECAST_SOURCE:
        return
    from .places import connect
    from .places.store import load_forecasts

    conn = connect(db_path)
    try:
        saved = load_forecasts(conn)
    finally:
        conn.close()
    FORECASTS.clear()
    FORECASTS.update({fid: saved[pid] for fid, pid in _FORECAST_SOURCE.items() if pid in saved})


def refresh_weather(max_age_minutes: float = 60) -> bool:
    """Download fresh forecasts if the saved ones are older than max_age_minutes.

    Returns True if anything changed. Network errors keep the old forecasts.
    """
    db_path = _db_path()
    if db_path is None or not _FORECAST_SOURCE:
        return False
    from .places import connect
    from .places.http import SourceError
    from .places.weather import refresh_forecasts

    conn = connect(db_path)
    try:
        updated = refresh_forecasts(conn, max_age_minutes=max_age_minutes)
    except SourceError:
        return False
    finally:
        conn.close()
    if updated:
        reload_forecasts()
    return bool(updated)


def trip_forecast(facility_id: str, start: str, end: str) -> list[dict] | None:
    """Forecast days covering the whole trip, or None if any trip day is outside the forecast."""
    forecast = FORECASTS.get(facility_id)
    if not forecast or date_error(start, end):
        return None
    by_date = {day["date"]: day for day in forecast["days"]}
    arrive, leave = date.fromisoformat(start), date.fromisoformat(end)
    days = [by_date.get((arrive + timedelta(days=i)).isoformat()) for i in range((leave - arrive).days + 1)]
    return days if all(days) else None


def current_conditions(facility_id: str) -> dict | None:
    """{temp_f, text, as_of} for the latest reading, e.g. 43.1, "Clear", "Fri 9:15 PM"."""
    from .places.weather import describe

    forecast = FORECASTS.get(facility_id)
    if not forecast or forecast.get("current_temp_f") is None:
        return None
    try:
        when = datetime.fromisoformat(forecast["local_time"])
        as_of = f"{when:%a} {when:%I:%M %p}".replace(" 0", " ")
    except ValueError:
        as_of = ""
    return {"temp_f": forecast["current_temp_f"], "text": describe(forecast.get("current_code")), "as_of": as_of}


def weather_text(code: int | None) -> str:
    from .places.weather import describe

    return describe(code)


PLACES = _with_cache(SAMPLE_PLACES)
BY_ID = {place["FacilityID"]: place for place in PLACES}
reload_forecasts()
CITIES = {
    "Salt Lake City, UT": (40.7608, -111.8910),
    "Provo, UT": (40.2338, -111.6585),
    "Ogden, UT": (41.2230, -111.9738),
    "Park City, UT": (40.6461, -111.4980),
    "St. George, UT": (37.0965, -113.5684),
    "Moab, UT": (38.5733, -109.5498),
    "Cedar City, UT": (37.6775, -113.0619),
    "Logan, UT": (41.7370, -111.8338),
    "Las Vegas, NV": (36.1699, -115.1398),
}
ACCESS = {
    "wheelchair": "Wheelchair friendly",
    "stroller": "Stroller friendly",
    "paved": "Paved paths",
    "restrooms": "Restrooms",
    "quiet": "Quieter setting",
    "shade": "Shade available",
    "medical": "Near medical services",
}
TYPES = list(dict.fromkeys(p["Type"] for p in PLACES))
ACTIVITIES = ["Hiking", "Camping", "Skiing", "Biking", "Water", "Scenic Drive", "Wildlife", "Stargazing"]


def date_error(start: str, end: str) -> str:
    try:
        arrive, leave = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return "Choose an arrival and departure date to plan your trip."
    if leave < arrive:
        return "Your leave date must be on or after your arrival date."
    if (leave - arrive).days > 365:
        return "Choose a trip of one year or less."
    return ""


def trip_months(start: str, end: str) -> list[int]:
    """One month index per trip day, so cross-month averages are weighted."""
    if date_error(start, end):
        return []
    arrive, leave = date.fromisoformat(start), date.fromisoformat(end)
    return [(arrive + timedelta(days=i)).month - 1 for i in range((leave - arrive).days + 1)]


def date_range(start: str, end: str) -> str:
    if date_error(start, end):
        return "your dates"
    arrive, leave = date.fromisoformat(start), date.fromisoformat(end)
    if arrive == leave:
        return f"{arrive:%b} {arrive.day}, {arrive.year}"
    if arrive.year != leave.year:
        return f"{arrive:%b} {arrive.day}, {arrive.year} – {leave:%b} {leave.day}, {leave.year}"
    if arrive.month == leave.month:
        return f"{arrive:%b} {arrive.day}–{leave.day}, {leave.year}"
    return f"{arrive:%b} {arrive.day} – {leave:%b} {leave.day}, {leave.year}"


def score_label(score: float) -> tuple[str, str]:
    if score >= 85:
        return "Great", "#1E5B2E"
    if score >= 70:
        return "Good", "#4D6B2A"
    if score >= 50:
        return "Fair", "#7A6A2E"
    return "Off-season", "#6B7280"


def crowd_label(crowds: float) -> str:
    return "Low" if crowds < 1.5 else "Moderate" if crowds < 2.5 else "Busy"


def distance_text(miles: float, metric: bool) -> str:
    return f"{round(miles * 1.609344):,} km" if metric else f"{round(miles):,} mi"


def temperature(value: float, metric: bool) -> str:
    return f"{round((value - 32) * 5 / 9)}°C" if metric else f"{round(value)}°F"


def elevation(value: int | None, metric: bool) -> str:
    if value is None:
        return "Not listed"
    return f"{round(value * 0.3048):,} m" if metric else f"{value:,} ft"


def rating_text(place: dict) -> str:
    if not place["Reviews"]:
        return "No rating yet"
    return f"★ {place['Rating']:.1f} ({place['Reviews']:,})"


def drive_time(hours: float) -> str:
    minutes = round(hours * 60)
    if minutes < 60:
        return f"{minutes} min"
    hrs, mins = divmod(minutes, 60)
    return f"{hrs} hr {mins} min" if mins else f"{hrs} hr"


@dataclass(frozen=True)
class TripStats:
    score: int
    crowds: float
    high_f: float
    miles: float

    @property
    def hours(self) -> float:
        return self.miles / 65


def compute(place: dict, months: list[int], origin: tuple[float, float],
            high_f: float | None = None) -> TripStats:
    """``high_f`` overrides the monthly-average high, e.g. with the forecast for the trip."""
    if not months:
        raise ValueError("A valid date range is required.")
    lat1, lon1, lat2, lon2 = map(math.radians, (*origin, place["FacilityLatitude"], place["FacilityLongitude"]))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    # A rough driving-distance multiplier, deliberately not presented as routing.
    miles = 3958.8 * 2 * math.asin(math.sqrt(min(1, max(0, a)))) * 1.3
    average = lambda key: sum(place[key][m] for m in months) / len(months)
    high = average("HighsF") if high_f is None else high_f
    return TripStats(round(average("Season")), average("Crowds"), high, miles)


def month_names(values: list[int], threshold: int) -> str:
    months = [MONTHS[i] for i, value in enumerate(values) if value >= threshold]
    return "all year" if len(months) == 12 else ", ".join(months)


def saved_ids(raw: str) -> list[str]:
    try:
        values = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(v for v in values if isinstance(v, str) and v in BY_ID))


def matches(place: dict, stats: TripStats, filters: list[str], favorites: list[str],
            radius: float = 0, rating: float = 0, drive: float = 0) -> bool:
    if radius and stats.miles > radius or rating and place["Rating"] < rating or drive and stats.hours > drive:
        return False
    types = [token.removeprefix("type:") for token in filters if token.startswith("type:")]
    activities = [token.removeprefix("activity:") for token in filters if token.startswith("activity:")]
    costs = [int(token.removeprefix("cost:")) for token in filters if token.startswith("cost:")]
    if types and place["Type"] not in types:
        return False
    if activities and not set(activities).intersection(place["Activities"]):
        return False
    if costs and place["CostTier"] not in costs:
        return False
    for token in filters:
        if token.startswith("access:") and not place["Access"].get(token.removeprefix("access:"), False):
            return False
    return not (
        "saved" in filters and place["FacilityID"] not in favorites
        or "good" in filters and stats.score < 70
        or "family" in filters and not place["FamilyFriendly"]
        or "dogs" in filters and not place["DogFriendly"]
        or "low_crowds" in filters and stats.crowds >= 2
        or "no_reservation" in filters and place["Reservation"]
    )


def packing_list(place: dict, stats: TripStats) -> list[str]:
    items = ["Refillable water bottle", "Sunscreen, sunglasses and a hat"]
    if stats.high_f >= 85:
        items += ["Extra water for hot, dry weather", "Light, breathable clothing"]
    elif stats.high_f <= 50:
        items += ["Warm layers, gloves and a warm hat"]
    else:
        items += ["Layers for cool mornings and evenings"]
    if (place["ElevationFt"] or 0) >= 7000 and stats.high_f > 50:
        items.append("A warm jacket for cold nights at elevation")
    for activity, item, include in [
        ("Hiking", "Sturdy shoes with good grip", True),
        ("Water", "Swimsuit, water shoes and a towel", stats.high_f >= 70),
        ("Skiing", "Ski goggles and a waterproof jacket", stats.high_f <= 50),
        ("Stargazing", "Headlamp with a red-light setting", True),
        ("Camping", "Camping gear", True),
    ]:
        if include and activity in place["Activities"]:
            items.append(item)
    if not place["Access"]["medical"]:
        items.append("First-aid kit and personal medications")
    return [*items, "Offline maps downloaded before you go"]
