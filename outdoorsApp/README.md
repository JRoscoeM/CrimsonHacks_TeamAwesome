# Utah Wayfinder

Finds Utah parks, campgrounds, and ski resorts that are a good fit for your trip dates. Built with [Reflex](https://reflex.dev).

All commands below run from this folder (the one with `rxconfig.py`). On Windows, use `py` where it says `python`.

## 1. API keys

1. Copy `.env.example` to `.env`.
2. Fill in the keys. Each one has a comment in `.env.example` with its sign-up link.

| Key | Needed for | Status |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | Ratings, reviews, weather, drive times, map | Have it |
| `RIDB_API_KEY` | Recreation.gov campgrounds | Have it |
| `NPS_API_KEY` | National parks and NPS campgrounds | Sign up (free) |
| `UDOT_API_KEY` | Road and canyon conditions | Sign up (free) |
| `NOAA_CDO_TOKEN`, `AIRNOW_API_KEY` | Typical weather, air quality | Optional |

`.env` is gitignored. **Never commit real keys.** Ask a teammate for the shared ones.

In code, read keys from `outdoorsApp/keys.py`. A key that isn't set is `None`:

```python
from outdoorsApp.keys import NPS_API_KEY
```

## 2. Build the places cache

The app reads parks, campgrounds, and ski resorts from a local SQLite file, `data/places.db`, rather than calling the APIs on every search. The file isn't committed, so run this once after cloning, and again whenever you want fresh data:

```
python -m outdoorsApp.places.seed
```

It downloads every source that has a key and skips the rest:

| Source | What | Key |
|---|---|---|
| `nps` | National parks, monuments, recreation areas | `NPS_API_KEY` |
| `nps_campgrounds` | NPS campgrounds | `NPS_API_KEY` |
| `ridb` | Recreation.gov campgrounds (duplicates of NPS ones are skipped) | `RIDB_API_KEY` |
| `osm` | State parks and ski resorts (OpenStreetMap) | none |
| `climate` | Each place's elevation and average high/low per month, from last year's weather records (Open-Meteo). Only fetches places that don't have it yet. The first run takes a few minutes because it's paced to stay under Open-Meteo's free limits. | none |
| `forecast` | Current conditions plus a 16-day forecast for every place (Open-Meteo) | none |

The app also refreshes forecasts by itself, in the background, when the saved ones are more than an hour old.

To refresh only some sources, run `python -m outdoorsApp.places.seed --only osm,ridb`. If a download fails, that source keeps its old data.

## 3. Query places

### From code

```python
from outdoorsApp.places import find_places, get_place, Kind

# All filters are optional and combine with AND.
places = find_places(
    kind=[Kind.NATIONAL_PARK, Kind.STATE_PARK],
    activities=["hiking"],          # must have all of these
    near=(40.76, -111.89),          # sorts nearest first and sets place.distance_mi
    within_mi=150,
    wheelchair=True,
)

zion = get_place("nps:zion")        # one place, including the raw API record
zion.to_dict()                      # plain dict for Reflex state
```

- **Kinds:** `national_park`, `national_monument`, `recreation_area`, `historic_site`, `state_park`, `ski_resort`, `campground`, `other`
- **Activity tags:** `hiking`, `camping`, `skiing`, `scenic_drive`, `stargazing`, `biking`, `fishing`, `boating`, `climbing`, `wildlife`, `horseback`, `swimming`, `off_road`

To turn a raw API record into a `Place`, use `parse_place(source, raw)`. `source` is one of the source names in the table in step 2.

### From a terminal

```
python -m outdoorsApp.places                                    # counts by kind and source
python -m outdoorsApp.places --kind campground --activity hiking --near 37.2,-112.99 --within 25
python -m outdoorsApp.places --text arches
python -m outdoorsApp.places --id nps:zion --raw                # one place, full record
```

### Things to know

- **Distances are straight-line miles.** Drive times will come from the Google Routes API.
- **Don't store Google ratings or reviews in the cache.** Google's terms don't allow it. Fetch them when a place is shown. Storing Google place IDs is allowed: use `set_google_place_id()`.
- **OSM places have no activity tags yet**, so state parks and ski resorts won't match an activity filter.

### How the UI uses the cache

`outdoorsApp/place_data.py` builds the app's `PLACES` list from two sources:

- **Curated samples** (`sample_places.json`). These keep all their hand-written details. When the cache has the same place, the sample also gets the cache's real photo and official website.
- **Every other place in the cache**, converted to the same format. Data we don't have yet gets an honest default: "No rating yet", "Check with the site" for cost, and elevation "Not listed". Seasonal scores, crowds and temperatures are borrowed from the nearest similar curated place, and the detail view says so.

**Weather**

- **Trips within the next 16 days** show the forecast high (for example "56°F forecast"), a day-by-day forecast in the detail view, and "Right now" conditions with the time of the reading.
- **Trips further out** show average highs for those months. Cache places use their own weather records. Curated places keep their hand-entered averages, which describe the area people visit rather than the park's center point.
- **Cache places also show** their real elevation, plus whatever the source provides: fees, campsite counts, phone numbers, hours and amenities.

Other things to know:

- **Restart the app after re-seeding.** The places and climate data are read once at startup. Forecasts update without a restart.
- **Card images** fall back to the artwork in `assets/landscapes/` when a place has no photo.
- **Results are capped at the top 60.** The caption still counts every place that matches.
- **To use only the curated samples**, set `WAYFINDER_SAMPLE_ONLY=1`. The tests in `tests/test_wayfinder.py` do this so their counts don't depend on your local cache.

## 4. Run the app

```
uv run reflex run
```

The app is at http://localhost:3000.
