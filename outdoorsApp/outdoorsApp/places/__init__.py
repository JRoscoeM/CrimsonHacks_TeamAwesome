"""Cached Utah places (parks, campgrounds, ski resorts) and helpers to query them.

    from outdoorsApp.places import find_places, get_place, Kind

    find_places(kind=Kind.CAMPGROUND, activities=["hiking"], near=(40.76, -111.89), within_mi=60)
    get_place("nps:zion")

Fill the cache first:  py -m outdoorsApp.places.seed
Query from a terminal: py -m outdoorsApp.places --help
"""

from .model import ACTIVITIES, KIND_LABELS, Kind, Place, haversine_mi
from .parsers import parse_place
from .store import connect, find_places, get_place, set_google_place_id, stats

__all__ = [
    "ACTIVITIES", "KIND_LABELS", "Kind", "Place", "connect", "find_places", "get_place",
    "haversine_mi", "parse_place", "set_google_place_id", "stats",
]
