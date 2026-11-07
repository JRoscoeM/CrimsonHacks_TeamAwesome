"""The ``Place`` record shared by every data source."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field


class Kind:
    """Values for ``Place.kind``."""

    NATIONAL_PARK = "national_park"
    NATIONAL_MONUMENT = "national_monument"
    RECREATION_AREA = "recreation_area"
    HISTORIC_SITE = "historic_site"
    STATE_PARK = "state_park"
    SKI_RESORT = "ski_resort"
    CAMPGROUND = "campground"
    OTHER = "other"


KIND_LABELS = {
    Kind.NATIONAL_PARK: "National Park",
    Kind.NATIONAL_MONUMENT: "National Monument",
    Kind.RECREATION_AREA: "Recreation Area",
    Kind.HISTORIC_SITE: "Historic Site",
    Kind.STATE_PARK: "State Park",
    Kind.SKI_RESORT: "Ski Resort",
    Kind.CAMPGROUND: "Campground",
    Kind.OTHER: "Other",
}

# Canonical activity tags. Source-specific names are mapped onto these by
# ``parsers.canonical_activities`` so filters work the same for every source.
ACTIVITIES = (
    "hiking", "camping", "skiing", "scenic_drive", "stargazing", "biking",
    "fishing", "boating", "climbing", "wildlife", "horseback", "swimming", "off_road",
)


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in miles."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Place:
    id: str                     # "<source>:<source_id>", e.g. "nps:zion"
    source: str                 # "nps", "nps_campgrounds", "ridb", "osm"
    source_id: str
    name: str
    kind: str                   # one of Kind.*
    lat: float
    lon: float
    designation: str = ""       # the source's own label, e.g. "National Park"
    description: str = ""
    url: str = ""
    image_url: str = ""         # primary photo (= images[0]["url"]), "" if none
    images: list[dict] = field(default_factory=list)  # [{url, title, alt, credit}], hot-linked
    park_code: str = ""         # NPS park code (also set on NPS campgrounds)
    activities: list[str] = field(default_factory=list)  # canonical tags
    amenities: list[str] = field(default_factory=list)
    wheelchair: bool | None = None   # None = unknown
    restrooms: bool | None = None
    reservable: bool | None = None
    google_place_id: str | None = None
    raw: dict = field(default_factory=dict, repr=False)  # original API record
    distance_mi: float | None = None  # set by find_places(near=...)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind.replace("_", " ").title())

    def has_activities(self, *tags: str) -> bool:
        return all(tag in self.activities for tag in tags)

    def distance_to(self, lat: float, lon: float) -> float:
        return haversine_mi(self.lat, self.lon, lat, lon)

    def to_dict(self, include_raw: bool = False) -> dict:
        """Plain dict, e.g. for Reflex state vars or JSON responses."""
        data = asdict(self)
        data["kind_label"] = self.kind_label
        if not include_raw:
            data.pop("raw")
        return data
