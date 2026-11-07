"""Local prototype fixtures and date-aware presentation helpers.

These are sample estimates, not live park information, forecasts, or routing data.
The Reflex application has no runtime dependency on the HTML mockup.
"""

import calendar
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


PLACES = json.loads(Path(__file__).with_name("sample_places.json").read_text())
BY_ID = {place["FacilityID"]: place for place in PLACES}
MONTHS = list(calendar.month_abbr)[1:]
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


def elevation(value: int, metric: bool) -> str:
    return f"{round(value * 0.3048):,} m" if metric else f"{value:,} ft"


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


def compute(place: dict, months: list[int], origin: tuple[float, float]) -> TripStats:
    if not months:
        raise ValueError("A valid date range is required.")
    lat1, lon1, lat2, lon2 = map(math.radians, (*origin, place["FacilityLatitude"], place["FacilityLongitude"]))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    # A rough driving-distance multiplier, deliberately not presented as routing.
    miles = 3958.8 * 2 * math.asin(math.sqrt(min(1, max(0, a)))) * 1.3
    average = lambda key: sum(place[key][m] for m in months) / len(months)
    return TripStats(round(average("Season")), average("Crowds"), average("HighsF"), miles)


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
    if place["ElevationFt"] >= 7000 and stats.high_f > 50:
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
