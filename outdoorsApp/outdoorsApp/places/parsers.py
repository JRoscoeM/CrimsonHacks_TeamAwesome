"""Turn raw API records into ``Place`` objects.

Every parser takes one raw record (a dict straight from the API) and returns a
``Place``, or ``None`` if the record is unusable (no name, no coordinates,
outside Utah). Use ``parse_place(source, raw)`` to dispatch by source.
"""

from __future__ import annotations

import html
import re

from .model import Kind, Place

# Utah's bounding box, padded a little.
_UT_LAT = (36.9, 42.1)
_UT_LON = (-114.1, -108.9)

_ACTIVITY_KEYWORDS = {
    "hiking": ("hiking", "walking", "backpacking"),
    "camping": ("camping", "campground"),
    "skiing": ("skiing", "snowboard", "ski "),
    "scenic_drive": ("scenic driving", "auto touring", "auto and atv", "scenic drive"),
    "stargazing": ("astronomy", "stargazing", "night sky"),
    "biking": ("biking", "cycling"),
    "fishing": ("fishing",),
    "boating": ("boating", "paddling", "kayak", "canoe", "rafting", "water ski"),
    "climbing": ("climbing", "canyoneering"),
    "wildlife": ("wildlife", "bird"),
    "horseback": ("horse",),
    "swimming": ("swimming",),
    "off_road": ("off highway", "off-highway", "ohv", "atv"),
}

_NPS_DESIGNATIONS = {
    "national park": Kind.NATIONAL_PARK,
    "national monument": Kind.NATIONAL_MONUMENT,
    "national recreation area": Kind.RECREATION_AREA,
}


def canonical_activities(names) -> list[str]:
    """Map free-form activity names (any source) to the canonical tags."""
    found = set()
    for name in names:
        text = f" {str(name).lower()} "
        for tag, keywords in _ACTIVITY_KEYWORDS.items():
            if any(k in text for k in keywords):
                if tag == "skiing" and "water ski" in text:
                    continue
                found.add(tag)
    return sorted(found)


def to_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # drop NaN


def clean_text(value) -> str:
    """Strip HTML tags and entities, collapse whitespace."""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def in_utah(lat: float | None, lon: float | None) -> bool:
    return (lat is not None and lon is not None
            and _UT_LAT[0] <= lat <= _UT_LAT[1] and _UT_LON[0] <= lon <= _UT_LON[1])


def nps_images(images) -> list[dict]:
    """NPS ``images`` -> [{url, title, alt, credit}]."""
    return [
        {"url": i["url"], "title": i.get("title", ""), "alt": i.get("altText") or i.get("title", ""),
         "credit": i.get("credit", "")}
        for i in images or [] if i.get("url")
    ]


def ridb_images(media) -> list[dict]:
    """RIDB ``MEDIA`` -> [{url, title, alt, credit}], images only, primary first."""
    items = [m for m in media or [] if m.get("URL") and (m.get("MediaType") or "Image").lower() == "image"]
    items.sort(key=lambda m: not m.get("IsPrimary"))
    return [
        {"url": m["URL"], "title": m.get("Title", ""),
         "alt": m.get("Description") or m.get("Title", ""), "credit": m.get("Credits", "")}
        for m in items
    ]


def _yes(value) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y")


# --- NPS ---------------------------------------------------------------------

def parse_nps_park(raw: dict) -> Place | None:
    """Record from NPS ``/parks``."""
    lat, lon = to_float(raw.get("latitude")), to_float(raw.get("longitude"))
    name = raw.get("fullName") or raw.get("name")
    if not name or not in_utah(lat, lon):
        return None
    designation = raw.get("designation") or ""
    lowered = designation.lower()
    kind = _NPS_DESIGNATIONS.get(lowered)
    if kind is None:
        kind = Kind.HISTORIC_SITE if "histor" in lowered or "trail" in lowered else Kind.OTHER
    code = raw.get("parkCode", "")
    images = nps_images(raw.get("images"))
    return Place(
        id=f"nps:{code}", source="nps", source_id=code, name=name, kind=kind, lat=lat, lon=lon,
        designation=designation, description=clean_text(raw.get("description")),
        url=raw.get("url", ""), image_url=images[0]["url"] if images else "", images=images,
        park_code=code,
        activities=canonical_activities(a.get("name", "") for a in raw.get("activities", [])),
        raw=raw,
    )


def parse_nps_campground(raw: dict) -> Place | None:
    """Record from NPS ``/campgrounds``."""
    lat, lon = to_float(raw.get("latitude")), to_float(raw.get("longitude"))
    if not raw.get("name") or not in_utah(lat, lon):
        return None
    amenities_raw = raw.get("amenities") or {}
    toilets = [t for t in amenities_raw.get("toilets", []) if t]
    restrooms = None
    if toilets:
        restrooms = not all(t.strip().lower() in ("none", "no") for t in toilets)
    access = (raw.get("accessibility") or {}).get("wheelchairAccess", "").strip()
    wheelchair = None
    if access:
        wheelchair = not access.lower().startswith(("no", "not ", "none"))
    amenities = sorted({
        key for key, value in amenities_raw.items()
        if value and value not in ("No", "None", ["None"], ["No"])
    })
    images = nps_images(raw.get("images"))
    return Place(
        id=f"nps_campgrounds:{raw['id']}", source="nps_campgrounds", source_id=raw["id"],
        name=raw["name"], kind=Kind.CAMPGROUND, lat=lat, lon=lon, designation="NPS Campground",
        description=clean_text(raw.get("description")),
        url=raw.get("url") or raw.get("reservationUrl", ""),
        image_url=images[0]["url"] if images else "", images=images,
        park_code=raw.get("parkCode", ""), activities=["camping"], amenities=amenities,
        wheelchair=wheelchair, restrooms=restrooms,
        reservable=bool(raw.get("reservationUrl")) or None, raw=raw,
    )


# --- Recreation.gov RIDB -----------------------------------------------------

def parse_ridb_facility(raw: dict) -> Place | None:
    """Record from RIDB ``/facilities?full=true``."""
    lat, lon = to_float(raw.get("FacilityLatitude")), to_float(raw.get("FacilityLongitude"))
    name = (raw.get("FacilityName") or "").strip()
    if not name or not in_utah(lat, lon) or raw.get("Enabled") is False:
        return None
    ftype = raw.get("FacilityTypeDescription") or ""
    activities = canonical_activities(a.get("ActivityName", "") for a in raw.get("ACTIVITY", []))
    kind = Kind.CAMPGROUND if ftype.lower() == "campground" else Kind.OTHER
    if kind == Kind.CAMPGROUND and "camping" not in activities:
        activities = sorted([*activities, "camping"])
    images = ridb_images(raw.get("MEDIA"))
    fid = str(raw.get("FacilityID"))
    return Place(
        id=f"ridb:{fid}", source="ridb", source_id=fid, name=name.title() if name.isupper() else name,
        kind=kind, lat=lat, lon=lon, designation=ftype,
        description=clean_text(raw.get("FacilityDescription")),
        url=f"https://www.recreation.gov/camping/campgrounds/{fid}" if kind == Kind.CAMPGROUND
        else raw.get("FacilityReservationURL", ""),
        image_url=images[0]["url"] if images else "", images=images, activities=activities,
        wheelchair=_yes(raw.get("FacilityADAAccess")) if raw.get("FacilityADAAccess") else None,
        reservable=_yes(raw.get("Reservable")), raw=raw,
    )


# --- OpenStreetMap (Overpass) ------------------------------------------------

def parse_osm_element(raw: dict) -> Place | None:
    """Element from an Overpass ``out center tags`` response."""
    tags = raw.get("tags") or {}
    name = tags.get("name")
    center = raw.get("center") or raw
    lat, lon = to_float(center.get("lat")), to_float(center.get("lon"))
    if not name or not in_utah(lat, lon):
        return None
    if tags.get("landuse") == "winter_sports":
        # OSM also tags snowmobile / non-motorized winter areas this way; those aren't resorts.
        if re.search(r"non-?motorized|snowmobile|recreation area", name, re.I):
            return None
        kind, activities, designation = Kind.SKI_RESORT, ["skiing"], "Ski Resort"
    else:
        kind, activities, designation = Kind.STATE_PARK, [], "State Park"
    osm_id = f"{raw.get('type')}/{raw.get('id')}"
    return Place(
        id=f"osm:{osm_id}", source="osm", source_id=osm_id, name=name, kind=kind, lat=lat, lon=lon,
        designation=designation, description=tags.get("description", ""),
        url=tags.get("website") or tags.get("contact:website", ""), activities=activities,
        wheelchair=_yes(tags.get("wheelchair")) if tags.get("wheelchair") else None,
        restrooms=_yes(tags.get("toilets")) if tags.get("toilets") else None, raw=raw,
    )


PARSERS = {
    "nps": parse_nps_park,
    "nps_campgrounds": parse_nps_campground,
    "ridb": parse_ridb_facility,
    "osm": parse_osm_element,
}


def parse_place(source: str, raw: dict) -> Place | None:
    """Parse one raw record from ``source`` (a key of ``PARSERS``)."""
    try:
        parser = PARSERS[source]
    except KeyError:
        raise ValueError(f"Unknown source {source!r}; expected one of {sorted(PARSERS)}") from None
    return parser(raw)
