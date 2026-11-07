"""Fill the places cache from the source APIs.

Run from the project folder (the one with rxconfig.py):

    py -m outdoorsApp.places.seed                 # every source that has a key
    py -m outdoorsApp.places.seed --only osm,ridb # just these

Sources and the key each needs (see .env.example):
    nps              National/state-run NPS units in Utah   NPS_API_KEY
    nps_campgrounds  NPS campgrounds in Utah                NPS_API_KEY
    ridb             Recreation.gov campgrounds in Utah     RIDB_API_KEY
    osm              State parks + ski resorts (OSM)        none

A source is only replaced after it downloads successfully, so a failed run
leaves the old data in place. Re-run whenever you want fresh data.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import keys
from .model import Kind, Place, haversine_mi
from .parsers import parse_place
from .store import connect, find_places, replace_source, stats

USER_AGENT = "UtahWayfinder/0.1 (CrimsonHacks project)"
NPS_BASE = "https://developer.nps.gov/api/v1"
RIDB_BASE = "https://ridb.recreation.gov/api/v1"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

OVERPASS_QUERY = """
[out:json][timeout:90];
area["ISO3166-2"="US-UT"][admin_level=4]->.ut;
(
  nwr["boundary"="protected_area"]["name"~"State Park$"](area.ut);
  nwr["leisure"="park"]["name"~"State Park$"](area.ut);
  nwr["landuse"="winter_sports"]["name"](area.ut);
);
out center tags;
"""


class SourceError(RuntimeError):
    pass


def _request_json(url: str, *, params: dict | None = None, headers: dict | None = None,
                  data: bytes | None = None, retries: int = 3):
    # Keys always go in headers, never the URL, so they can't leak into error messages.
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise SourceError(f"HTTP {error.code} from {url.split('?')[0]}") from None
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            raise SourceError(f"Couldn't reach {url.split('?')[0]}: {error}") from None
    raise SourceError("unreachable")


# --- Fetchers: each returns a list of raw records ----------------------------

def _fetch_nps(endpoint: str) -> list[dict]:
    records, start = [], 0
    while True:
        page = _request_json(f"{NPS_BASE}/{endpoint}",
                             params={"stateCode": "UT", "limit": 50, "start": start},
                             headers={"X-Api-Key": keys.NPS_API_KEY})
        data = page.get("data", [])
        records += data
        start += len(data)
        if not data or start >= int(page.get("total", 0)):
            return records


def fetch_nps_parks() -> list[dict]:
    return _fetch_nps("parks")


def fetch_nps_campgrounds() -> list[dict]:
    return _fetch_nps("campgrounds")


def fetch_ridb() -> list[dict]:
    records, offset = [], 0
    while True:
        page = _request_json(f"{RIDB_BASE}/facilities",
                             params={"state": "UT", "limit": 50, "offset": offset, "full": "true"},
                             headers={"apikey": keys.RIDB_API_KEY, "Accept": "application/json"})
        data = page.get("RECDATA", [])
        records += data
        offset += len(data)
        total = page.get("METADATA", {}).get("RESULTS", {}).get("TOTAL_COUNT", 0)
        print(f"  ridb: {offset}/{total}", end="\r", flush=True)
        if not data or offset >= total:
            print()
            return records
        time.sleep(1.3)  # RIDB allows about 50 requests a minute


def fetch_osm() -> list[dict]:
    body = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode()
    return _request_json(OVERPASS_URL, data=body).get("elements", [])


# --- Clean-up ----------------------------------------------------------------

def _normalize_name(name: str) -> str:
    drop = {"campground", "camp", "group", "site", "the", "cg", "loop", "area"}
    words = "".join(c if c.isalnum() else " " for c in name.lower()).split()
    return " ".join(w for w in words if w not in drop)


def dedupe_by_name(places: list[Place]) -> list[Place]:
    """OSM often has several elements for one park (boundary + park polygon)."""
    seen, result = set(), []
    order = {"relation": 0, "way": 1, "node": 2}
    for place in sorted(places, key=lambda p: order.get(p.source_id.split("/")[0], 3)):
        key = (place.kind, _normalize_name(place.name))
        if key not in seen:
            seen.add(key)
            result.append(place)
    return result


def drop_overlaps(places: list[Place], existing: list[Place], *, max_mi: float = 0.3) -> list[Place]:
    """Skip RIDB campgrounds already covered by an NPS campground nearby with a similar name."""
    kept = []
    for place in places:
        name = _normalize_name(place.name)
        duplicate = any(
            other.kind == place.kind
            and haversine_mi(place.lat, place.lon, other.lat, other.lon) <= max_mi
            and (name == _normalize_name(other.name) or not name)
            for other in existing
        )
        if not duplicate:
            kept.append(place)
    return kept


SOURCES = {
    # name: (fetcher, required key attribute or None)
    "nps": (fetch_nps_parks, "NPS_API_KEY"),
    "nps_campgrounds": (fetch_nps_campgrounds, "NPS_API_KEY"),
    "ridb": (fetch_ridb, "RIDB_API_KEY"),
    "osm": (fetch_osm, None),
}


def seed(only: list[str] | None = None, db_path: str | None = None) -> dict:
    conn = connect(db_path)
    results = {}
    for source in only or list(SOURCES):
        fetch, key_name = SOURCES[source]
        if key_name and not getattr(keys, key_name):
            print(f"- {source}: skipped ({key_name} isn't set in .env)")
            results[source] = "skipped"
            continue
        print(f"- {source}: downloading...")
        try:
            raw_records = fetch()
        except SourceError as error:
            print(f"- {source}: FAILED, kept existing data ({error})")
            results[source] = "failed"
            continue
        places = [p for p in (parse_place(source, r) for r in raw_records) if p]
        if source == "osm":
            places = dedupe_by_name(places)
        if source == "ridb":
            places = [p for p in places if p.kind == Kind.CAMPGROUND]
            nps_campgrounds = find_places(source="nps_campgrounds", limit=None, conn=conn)
            before = len(places)
            places = drop_overlaps(places, nps_campgrounds)
            if before != len(places):
                print(f"  ridb: skipped {before - len(places)} already covered by NPS campgrounds")
        count = replace_source(conn, source, places)
        print(f"- {source}: saved {count} places (from {len(raw_records)} records)")
        results[source] = count
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help=f"comma-separated subset of: {', '.join(SOURCES)}")
    parser.add_argument("--db", help="database path (default: data/places.db)")
    args = parser.parse_args(argv)
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    unknown = set(only or []) - set(SOURCES)
    if unknown:
        parser.error(f"unknown source(s): {', '.join(sorted(unknown))}")
    results = seed(only, args.db)
    summary = stats(connect(args.db))
    print(f"\nCache now holds {summary['total']} places: {summary['by_kind']}")
    return 1 if "failed" in results.values() else 0


if __name__ == "__main__":
    sys.exit(main())
