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

## 4. Run the app

```
uv run reflex run
```

The app is at http://localhost:3000.

## TODO: connect the places cache to the UI

Do this after the in-progress `outdoorsApp/outdoorsApp.py` changes are pushed, so they don't conflict. Everything below goes in `outdoorsApp.py`. The `places` package it relies on is already done.

**State and data**
- [ ] Import `Kind`, `Place`, `connect` and `find_places` from `.places`.
- [ ] Add a `PlaceCard` dataclass for Reflex state: `id`, `name`, `kind_label`, `image_url`, `image_alt`, `credit`, `url`, `miles`, `km`, `gradient`, `tags: list[str]`. Add a `to_card(place)` helper that fills it from a `Place`.
- [ ] State vars: `origin` (default `"Salt Lake City"`), `types`, `activities`, `access` (lists of selected filter labels), `preset`, `places: list[PlaceCard]`, `total`, `cache_empty`.
- [ ] Add a `_refresh()` helper that calls `find_places(kind=..., activities=..., near=ORIGINS[origin], wheelchair=..., restrooms=..., limit=None)`, keeps the 60 closest results, and sets `cache_empty` when the database has no rows.
- [ ] Event handlers that each end by calling `_refresh()`: `load_places` (run on page load: `app.add_page(..., on_load=State.load_places)`), `set_origin`, `toggle_filter(group, label, checked)`, `apply_preset(name)` (tapping the active pill again clears it), and `clear_filters`.

**Header**
- [ ] Replace the "Starting from" text input with an `rx.select` of starting cities (`ORIGINS`: Salt Lake City, Ogden, Provo, Park City, Logan, Moab, Cedar City, St. George), each with its coordinates.
- [ ] Disable "📍 Near me" until browser location is connected. Change the hint to say distances are straight-line for now.

**Filters sidebar**
- [ ] Bind the checkboxes to state with `checked=State.<group>.contains(label)` and `on_change=lambda checked: State.toggle_filter(group, label, checked)`. Build each one in its own helper function, so every lambda captures its own label.
- [ ] Type options map to place kinds: "National Park / Monument" covers national parks, monuments, recreation areas and historic sites. Then State Park, Ski Resort and Campground.
- [ ] Activities: Hiking, Camping, Skiing, Scenic Drive, Stargazing, Fishing.
- [ ] Accessibility: Wheelchair friendly and Restrooms. Drop "Stroller friendly": no source has that data.
- [ ] Show "Good for your dates" and "Extras" as disabled with a "coming soon" note until weather, Google Places and crowd data exist.
- [ ] Wire "Clear all" to `clear_filters`. Remove "Show results", since the filters apply instantly.

**Results**
- [ ] Render the grid with `rx.foreach(State.places, place_card)`. `place_card` receives a Var, so use `rx.cond` and `rx.foreach` instead of Python `if` and loops.
- [ ] Card image: show `image_url` if there is one, otherwise the per-kind gradient. Overlay the photo credit (`📷 credit`) when present.
- [ ] Show distance with `rx.cond(State.metric, place.km, place.miles)`.
- [ ] Show activity tags as badges (up to 4).
- [ ] Make "Details" a link to `place.url` that opens in a new tab.
- [ ] Remove the placeholder rating, drive time, weather, crowds and MATCH score until that data is real.
- [ ] Quick-filter pills: Parks, Skiing, Camping, Hiking, highlighted when active.
- [ ] Result count text: "N places, nearest first from {origin}", plus "(showing the closest 60)" when there are more. If the cache is empty, show a callout telling people to run the seed.
