"""Utah Wayfinder: a native Reflex implementation of the visual prototype.

The HTML mockup is only a design reference. Sample content and artwork live in
independent local fixtures; all interactions below use Reflex state and events.
"""

import asyncio
import json
from datetime import date, timedelta

import reflex as rx
from reflex.style import set_color_mode

from .place_data import (
    ACTIVITIES, BY_ID, CITIES, MONTHS, PLACES, TYPES,
    compute, crowd_label, current_conditions, date_error, date_range, distance_text, drive_time,
    elevation, landscape, matches, month_names, packing_list, rating_text,
    saved_ids, score_label, temperature, trip_forecast, trip_months, weather_text,
)
from .place_data import drive_for, find_location, load_drives, load_google, prefetch_google
from .places.http import SourceError
from .place_data import refresh_weather as refresh_saved_forecasts

MAX_RESULTS = 60  # cards/pins rendered at once; the caption still counts every match

BG, INK, MUTED, LINE = "#F5F0E6", "#1F2A1F", "#56604F", "#DDD5C4"
BRAND, ACCENT, ACCENT_SOFT, CARD = "#2F5233", "#3B6E4A", "#E4EEDF", "#FFFFFF"
SHADOW = "0 1px 3px rgba(0,0,0,.08), 0 4px 14px rgba(0,0,0,.06)"
GRADIENT = "linear-gradient(135deg, #1F3B24, #2F5233 55%, #4A6B45)"
CONTROL = dict(
    min_height="44px", border=f"1px solid {LINE}", border_radius="10px",
    background=CARD, color=INK, padding="9px 12px", font_size="0.9rem",
)
BUTTON = dict(
    min_height="44px", border_radius="10px", font_weight="700",
    cursor="pointer", _hover={"filter": "brightness(.96)"},
)
COMPARISON_ROWS = [
    ("Score for your dates", "score_text"), ("Rating", "rating"),
    ("Estimated drive", "drive_full"), ("High for your dates", "weather"),
    ("Crowds", "crowds"), ("Busiest months", "busy"), ("Cost", "cost"),
    ("Reservation", "reservation"), ("Dogs", "dogs"), ("Activities", "activities_text"), ("Quieter visit", "quiet_time"),
]


class State(rx.State):
    metric: bool = False
    show_map: bool = False
    selected_places: list[str] = []
    favorite_storage: str = rx.LocalStorage("[]", name="uw-favs")
    active_filters: list[str] = []
    radius: str = "0"
    min_rating: str = "0"
    max_drive: str = "0"
    sort_by: str = "score"
    arrive: str = (date.today() + timedelta(days=7)).isoformat()
    leave: str = (date.today() + timedelta(days=10)).isoformat()
    location_text: str = "Salt Lake City, UT"
    origin_name: str = "Salt Lake City, UT"
    origin_lat: float = 40.7608
    origin_lon: float = -111.891
    location_note: str = 'Type a city, address or landmark and press Enter, or tap "Near me".'
    locating: bool = False
    filters_open: bool = False
    detail_open: bool = False
    detail_id: str = "zion"
    # Bumped when background data arrives, so the vars that use it recompute.
    weather_version: int = 0
    drive_version: int = 0
    google_version: int = 0

    @rx.event(background=True)
    async def refresh_weather(self):
        """On page load: download fresh forecasts if the saved ones are over an hour old."""
        if await asyncio.to_thread(refresh_saved_forecasts):
            async with self:
                self.weather_version += 1

    @rx.event(background=True)
    async def load_drives(self):
        """Road drive times from the current origin (saved, or fetched once from OSRM)."""
        async with self:
            lat, lon = self.origin_lat, self.origin_lon
        if await asyncio.to_thread(load_drives, lat, lon):
            async with self:
                self.drive_version += 1

    @rx.event(background=True)
    async def load_google(self, place_id: str):
        """Google rating and reviews for one place (kept in memory, never stored)."""
        if await asyncio.to_thread(load_google, place_id):
            async with self:
                self.google_version += 1

    @rx.event(background=True)
    async def prefetch_google(self):
        """With GOOGLE_RATINGS=all, look up every place once per app run."""
        if await asyncio.to_thread(prefetch_google):
            async with self:
                self.google_version += 1

    @rx.event
    def set_location_text(self, value: str):
        self.location_text = value

    @rx.event
    def set_arrive(self, value: str):
        self.arrive = value

    @rx.event
    def set_leave(self, value: str):
        self.leave = value

    @rx.event
    def set_radius(self, value: str):
        if value in {"0", "25", "50", "100", "200", "300"}:
            self.radius = value

    @rx.event
    def set_min_rating(self, value: str):
        if value in {"0", "4.5", "4.7"}:
            self.min_rating = value

    @rx.event
    def set_max_drive(self, value: str):
        if value in {"0", "1", "2", "4"}:
            self.max_drive = value

    @rx.event
    def set_sort_by(self, value: str):
        if value in {"score", "drive", "rating", "crowds"}:
            self.sort_by = value

    @rx.event
    def set_filters_open(self, value: bool):
        self.filters_open = value

    @rx.event
    def set_detail_open(self, value: bool):
        self.detail_open = value

    @rx.event
    def set_units(self, metric: bool):
        self.metric = metric

    @rx.event
    def toggle_view(self):
        self.show_map = not self.show_map

    @rx.event
    def toggle_filter(self, token: str):
        if token in self.active_filters:
            self.active_filters = [item for item in self.active_filters if item != token]
        else:
            self.active_filters = [*self.active_filters, token]

    @rx.event
    def clear_filters(self):
        self.active_filters = []
        self.radius = self.min_rating = self.max_drive = "0"

    @rx.event
    def toggle_place(self, place_id: str):
        if place_id not in BY_ID:
            return
        if place_id in self.selected_places:
            self.selected_places = [item for item in self.selected_places if item != place_id]
        elif len(self.selected_places) >= 3:
            return rx.toast.info("You can compare up to 3 places. Remove one to add another.")
        else:
            self.selected_places = [*self.selected_places, place_id]

    @rx.event
    def clear_comparison(self):
        self.selected_places = []

    @rx.event
    def toggle_favorite(self, place_id: str):
        if place_id not in BY_ID:
            return
        favorites = self.favorites
        if place_id in favorites:
            favorites = [item for item in favorites if item != place_id]
        else:
            favorites = [*favorites, place_id]
        self.favorite_storage = json.dumps(favorites)

    @rx.event
    def open_details(self, place_id: str):
        if place_id in BY_ID:
            self.detail_id = place_id
            self.detail_open = True
            return State.load_google(place_id)

    @rx.event
    def resolve_location(self, value: str):
        """Preset cities resolve instantly; anything else is looked up as an address."""
        text = value.strip()
        if not text or text == self.origin_name:
            self.location_text = self.origin_name
            return
        query = text.lower().split(",")[0].strip()
        for name, coordinates in CITIES.items():
            if query and name.lower().split(",")[0] == query:
                self.location_text = self.origin_name = name
                self.origin_lat, self.origin_lon = coordinates
                self.location_note = "Drive times are by road and approximate."
                return State.load_drives
        self.locating = True
        self.location_note = f"Searching for “{text}”… Still using {self.origin_name}."
        return State.search_location(text)

    @rx.event
    def location_key(self, key: str):
        if key == "Enter":
            return State.resolve_location(self.location_text)

    @rx.event(background=True)
    async def search_location(self, query: str):
        """Geocode a typed address/town/landmark (free OpenStreetMap search), then load drive times."""
        try:
            found = await asyncio.to_thread(find_location, query)
            error = None
        except SourceError:
            found, error = None, "Couldn't reach the address search"
        async with self:
            self.locating = False
            if self.location_text.strip() != query:  # the user typed something else meanwhile
                return
            if not found:
                reason = error or f"Couldn't find “{query}”. Try a town, address or landmark"
                self.location_note = f"{reason}. Still using {self.origin_name}."
                return
            self.origin_lat, self.origin_lon = found["lat"], found["lon"]
            self.origin_name = self.location_text = found["label"]
            self.location_note = f"Using {found['label']}. Loading drive times…"
            lat, lon = self.origin_lat, self.origin_lon
        loaded = await asyncio.to_thread(load_drives, lat, lon)
        async with self:
            if loaded:
                self.drive_version += 1
            if (self.origin_lat, self.origin_lon) == (lat, lon):
                self.location_note = f"Using {self.origin_name}. Drive times are by road and approximate."

    @rx.event
    def locate(self):
        self.locating = True
        self.location_note = "Finding your location…"
        return rx.call_script(
            """new Promise(resolve => {
                if (!navigator.geolocation) {
                    resolve({error: "Location is unavailable in this browser."}); return;
                }
                navigator.geolocation.getCurrentPosition(
                    p => resolve({lat: p.coords.latitude, lon: p.coords.longitude}),
                    () => resolve({error: "Could not access your location. Choose a city instead."}),
                    {timeout: 8000, maximumAge: 300000}
                );
            })""",
            callback=State.receive_location,
        )

    @rx.event
    def receive_location(self, result: dict):
        self.locating = False
        if not isinstance(result, dict) or "error" in result:
            self.location_note = (result.get("error") if isinstance(result, dict) else None) or "Location unavailable. Choose a city."
            return
        try:
            lat, lon = float(result["lat"]), float(result["lon"])
        except (KeyError, ValueError, TypeError):
            self.location_note = "Location unavailable. Choose a city."
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            self.location_note = "Location unavailable. Choose a city."
            return
        self.origin_lat, self.origin_lon = lat, lon
        self.origin_name = self.location_text = "Your location"
        self.location_note = "Using your location. Drive times are by road and approximate."
        return State.load_drives

    @rx.var
    def favorites(self) -> list[str]:
        return saved_ids(self.favorite_storage)

    @rx.var
    def date_warning(self) -> str:
        return date_error(self.arrive, self.leave)

    @rx.var
    def trip_label(self) -> str:
        return date_range(self.arrive, self.leave)

    @rx.var
    def filter_count(self) -> int:
        return len(self.active_filters) + sum(value != "0" for value in (self.radius, self.min_rating, self.max_drive))

    @rx.var
    def selected_names(self) -> str:
        return " · ".join(BY_ID[item]["FacilityName"] for item in self.selected_places if item in BY_ID)

    def _forecast(self, place: dict) -> list[dict] | None:
        _ = self.weather_version  # dependency: recompute when forecasts refresh
        return trip_forecast(place["FacilityID"], self.arrive, self.leave)

    def _stats(self, place: dict):
        months = trip_months(self.arrive, self.leave) or [date.today().month - 1]
        forecast = self._forecast(place)
        high = sum(day["high_f"] for day in forecast) / len(forecast) if forecast else None
        _ = self.drive_version  # dependency: recompute when drive times arrive
        drive = drive_for(self.origin_lat, self.origin_lon, place["FacilityID"])
        return compute(place, months, (self.origin_lat, self.origin_lon), high_f=high, drive=drive)

    def _view(self, place: dict) -> dict[str, str]:
        _ = self.google_version  # dependency: ratings/reviews update in place
        stats = self._stats(place)
        forecast = self._forecast(place) is not None
        now = current_conditions(place["FacilityID"])
        label, color = score_label(stats.score)
        tags = []
        if stats.crowds >= 2.5:
            tags.append("Peak season")
        if place["Reservation"]:
            tags.append("Reservation")
        if place["DogFriendly"]:
            tags.append("Dogs welcome")
        view = {
            "id": place["FacilityID"], "name": place["FacilityName"], "kind": place["Type"],
            "description": place["FacilityDescription"],
            "image": place.get("Image") or landscape(place["Type"]),
            "image_credit": place.get("ImageCredit", ""),
            "url": place.get("Url", ""),
            "estimate_note": place.get("EstimateNote", ""),
            "score": str(stats.score), "score_label": label, "score_color": color,
            "score_text": f"{stats.score}/100 · {label}",
            "rating": rating_text(place),
            "drive": drive_time(stats.hours) + ("" if stats.routed else " (est.)"),
            "drive_full": f"{drive_time(stats.hours)} · {distance_text(stats.miles, self.metric)}"
                          + (" by road" if stats.routed else " (estimate)"),
            "maps_url": place.get("MapsUrl", ""),
            "review_source": "Reviews from Google" if place.get("ReviewSource") == "Google"
                             else "Sample reviews",
            "weather": temperature(stats.high_f, self.metric) + (" forecast" if forecast else ""),
            "weather_kind": "Forecast highs" if forecast else "Average highs",
            "now": (f"{temperature(now['temp_f'], self.metric)}"
                    + (f" · {now['text']}" if now["text"] else "")
                    + (f" · as of {now['as_of']}" if now["as_of"] else "")) if now else "",
            "hours": place.get("Hours", ""), "phone": place.get("Phone", ""),
            "campsites": place.get("Campsites", ""), "amenities_text": place.get("AmenitiesText", ""),
            "crowds": crowd_label(stats.crowds),
            "cost": place["Cost"], "elevation": elevation(place["ElevationFt"], self.metric),
            "reservation": "Needed" if place["Reservation"] else "Not needed for entry",
            "dogs": "Allowed; rules vary" if place["DogFriendly"] else "Very limited",
            "busy": month_names(place["Crowds"], 3) or "Rarely busy",
            "best": month_names(place["Season"], 85) or "Check seasonal conditions",
            "quiet_time": place["QuietTime"], "tip": place["Tip"],
            "activities_text": ", ".join(place["Activities"]),
            "peak": "yes" if stats.crowds >= 2.5 else "no",
            "map_x": f"{((place['FacilityLongitude'] + 114.05) * 100 + 20) / 541 * 100:.2f}%",
            "map_y": f"{((42 - place['FacilityLatitude']) * 100 + 20) / 540 * 100:.2f}%",
        }
        for i in range(4):
            view[f"tag{i}"] = tags[i] if i < len(tags) else ""
        for _, key in COMPARISON_ROWS:
            view[key + "_best"] = "no"
        return view

    def _matching(self) -> list[dict]:
        """Every place that passes the filters, sorted. Not a var, so it isn't sent to the browser."""
        if self.date_warning:
            return []
        candidates = [
            (place, self._stats(place)) for place in PLACES
        ]
        candidates = [
            (place, stats) for place, stats in candidates
            if matches(place, stats, self.active_filters, self.favorites,
                       float(self.radius), float(self.min_rating), float(self.max_drive))
        ]
        sorters = {
            "score": lambda item: (-item[1].score, -item[0]["Rating"], item[1].miles),
            "drive": lambda item: (item[1].miles, -item[1].score),
            "rating": lambda item: (-item[0]["Rating"], -item[1].score),
            "crowds": lambda item: (item[1].crowds, -item[1].score),
        }
        candidates.sort(key=sorters.get(self.sort_by, sorters["score"]))
        return [place for place, _ in candidates]

    @rx.var
    def results(self) -> list[dict[str, str]]:
        return [self._view(place) for place in self._matching()[:MAX_RESULTS]]

    @rx.var
    def result_caption(self) -> str:
        count = len(self._matching())
        radius = f" · within {distance_text(float(self.radius), self.metric)}" if self.radius != "0" else ""
        shown = f" · showing the top {MAX_RESULTS}" if count > MAX_RESULTS else ""
        return (f"{count} {'place' if count == 1 else 'places'} for {self.trip_label} · "
                f"from {self.origin_name}{radius}{shown}")

    @rx.var
    def detail(self) -> dict[str, str]:
        return self._view(BY_ID[self.detail_id])

    @rx.var
    def detail_facts(self) -> list[dict[str, str]]:
        facts = [{"label": label, "value": self.detail[key]} for label, key in [
            ("Estimated drive", "drive_full"), ("Rating", "rating"), ("Cost", "cost"),
            ("Elevation", "elevation"), ("Reservation", "reservation"), ("Dogs", "dogs"),
        ]]
        # From the places cache, when the source has them.
        facts += [{"label": label, "value": self.detail[key]} for label, key in [
            ("Campsites", "campsites"), ("Phone", "phone"), ("Hours", "hours"), ("Amenities", "amenities_text"),
        ] if self.detail[key]]
        return facts

    @rx.var
    def detail_forecast(self) -> list[dict[str, str]]:
        """Day-by-day forecast for the trip (empty if the trip is beyond the 16-day forecast)."""
        days = self._forecast(BY_ID[self.detail_id]) or []
        return [
            {"day": f"{date.fromisoformat(d['date']):%a %b} {date.fromisoformat(d['date']).day}",
             "temps": f"{temperature(d['high_f'], self.metric)} / {temperature(d['low_f'], self.metric)}",
             "text": weather_text(d["code"]),
             "rain": f"{d['precip_pct']}% rain" if d.get("precip_pct") else ""}
            for d in days
        ]

    @rx.var
    def detail_months(self) -> list[dict[str, str]]:
        place = BY_ID[self.detail_id]
        selected = set(trip_months(self.arrive, self.leave))
        return [
            {
                "name": MONTHS[i], "short": MONTHS[i][0],
                "height": f"{max(4, round(place['Season'][i] * .55))}px",
                "color": score_label(place["Season"][i])[1],
                "dots": "•" * place["Crowds"][i],
                "background": ACCENT_SOFT if i in selected else "transparent",
                "outline": f"2px solid {ACCENT}" if i in selected else "none",
                "description": f"{MONTHS[i]}: {place['Season'][i]}/100, {crowd_label(place['Crowds'][i]).lower()} crowds"
                               + (", your trip" if i in selected else ""),
            }
            for i in range(12)
        ]

    @rx.var
    def detail_activities(self) -> list[str]:
        return BY_ID[self.detail_id]["Activities"]

    @rx.var
    def detail_things(self) -> list[str]:
        return BY_ID[self.detail_id]["ThingsToDo"]

    @rx.var
    def detail_packing(self) -> list[str]:
        place = BY_ID[self.detail_id]
        return packing_list(place, self._stats(place))

    @rx.var
    def detail_expectations(self) -> list[str]:
        place, view = BY_ID[self.detail_id], self.detail
        items = [
            f"Weather: {view['weather_kind'].lower()} near {view['weather'].removesuffix(' forecast')} for your dates.",
            f"Crowds: {view['crowds'].lower()}. Busiest months: {view['busy']}.",
        ]
        if place["ElevationFt"] is not None:
            items.append(f"Elevation: {view['elevation']}."
                         + (" Take time to adjust to the altitude." if place["ElevationFt"] >= 7000 else ""))
        if place["ReservationNote"]:
            items.append("Reservations: " + place["ReservationNote"])
        items.append(f"Getting there: about {view['drive_full']} from {self.origin_name}.")
        if self._stats(place).score < 50:
            items.append("Off-season: some roads, tours or services may be closed.")
        return items

    @rx.var
    def detail_reviews(self) -> list[dict[str, str]]:
        return [
            {"who": who, "stars": "★" * stars + "☆" * (5 - stars), "text": text,
             "label": f"{stars} out of 5 stars"}
            for who, stars, text in BY_ID[self.detail_id]["UserReviews"]
        ]

    @rx.var
    def comparison(self) -> list[dict[str, str]]:
        places = [BY_ID[item] for item in self.selected_places if item in BY_ID]
        views = [self._view(place) for place in places]
        if len(places) > 1:
            stats = [self._stats(place) for place in places]
            ranked = {
                "score_text": ([s.score for s in stats], max),
                "rating": ([p["Rating"] for p in places], max),
                "drive_full": ([s.miles for s in stats], min),
                "crowds": ([s.crowds for s in stats], min),
                "cost": ([p["CostTier"] for p in places], min),
            }
            for key, (values, choose) in ranked.items():
                known = [v for v in values if v is not None]  # e.g. cost unknown for cache places
                if len(set(known)) > 1:
                    best = choose(known)
                    for view, value in zip(views, values):
                        if value == best:
                            view[key + "_best"] = "yes"
        return views

    @rx.var
    def origin_marker(self) -> dict[str, str]:
        x = ((self.origin_lon + 114.05) * 100 + 20) / 541 * 100
        y = ((42 - self.origin_lat) * 100 + 20) / 540 * 100
        return {"x": f"{x:.2f}%", "y": f"{y:.2f}%",
                "display": "block" if 0 < x < 100 and 0 < y < 100 else "none"}


def small_text(text, **props) -> rx.Component:
    return rx.text(text, font_size="0.8rem", color=MUTED, **props)


def primary_button(label, **props) -> rx.Component:
    return rx.button(label, background=BRAND, color="white", **BUTTON, **props)


def secondary_button(label, **props) -> rx.Component:
    return rx.button(label, background=CARD, color=INK, border=f"1px solid {LINE}", **BUTTON, **props)


def select_control(options, value, handler, label, **props) -> rx.Component:
    return rx.el.select(
        *[rx.el.option(text, value=key) for key, text in options],
        value=value, on_change=handler, aria_label=label, **CONTROL, **props,
    )


def brand() -> rx.Component:
    return rx.hstack(
        rx.el.svg(
            rx.el.circle(cx="20", cy="20", r="18", fill="none", stroke="white", stroke_width="2.5"),
            rx.el.polygon(points="20,6 25,20 20,34 15,20", fill="white"),
            rx.el.polygon(points="20,6 25,20 15,20", fill="#E8DCC0"),
            width="40", height="40", view_box="0 0 40 40", aria_hidden=True, flex_shrink="0",
        ),
        rx.vstack(
            rx.heading("Utah Wayfinder", size=rx.breakpoints(initial="4", sm="5"), color="white"),
            spacing="0", align="start",
        ),
        spacing="3", align="center",
    )


def units() -> rx.Component:
    return rx.hstack(
        *[
            rx.button(
                label, on_click=State.set_units(metric),
                background=rx.cond(State.metric == metric, CARD, "transparent"),
                color=rx.cond(State.metric == metric, BRAND, "white"),
                aria_pressed=State.metric == metric, border="0", border_radius="999px",
                min_height="38px", padding="0 12px", font_weight="700", cursor="pointer",
            )
            for label, metric in [("°F · mi", False), ("°C · km", True)]
        ],
        spacing="0", padding="3px", background="rgba(255,255,255,.18)",
        border_radius="999px", flex_shrink="0", role="group", aria_label="Units",
    )


def date_field(label: str, field_id: str, value, handler) -> rx.Component:
    return rx.vstack(
        rx.el.label(label, html_for=field_id, color=MUTED, font_size="0.8rem", font_weight="700"),
        rx.el.input(id=field_id, type="date", value=value, on_change=handler,
                    width="100%", min_width="0", **CONTROL),
        spacing="1", align="start", width="100%", min_width="0",
    )


def header() -> rx.Component:
    return rx.el.header(
        rx.vstack(
            rx.flex(brand(), units(), justify="between", align="center", gap="14px", wrap="wrap", width="100%"),
            rx.grid(
                rx.vstack(
                    rx.el.label("Starting from", html_for="origin", font_size="0.8rem", font_weight="700", color=MUTED),
                    rx.hstack(
                        rx.el.input(
                            id="origin", list="cities", value=State.location_text,
                            on_change=State.set_location_text, on_blur=State.resolve_location,
                            on_key_down=State.location_key,
                            placeholder="City, address or landmark", enter_key_hint="search",
                            auto_complete="off", width="100%", min_width="0", **CONTROL,
                        ),
                        rx.el.datalist(*[rx.el.option(value=name) for name in CITIES], id="cities"),
                        rx.button(
                            rx.cond(State.locating, "Locating…", "Near me"), on_click=State.locate,
                            disabled=State.locating, background=ACCENT_SOFT, color=ACCENT,
                            border=f"1px solid {ACCENT}", white_space="nowrap", **BUTTON,
                        ),
                        spacing="2", width="100%",
                    ),
                    small_text(State.location_note, role="status"),
                    rx.flex(
                        rx.el.label("Search within", html_for="radius", font_size="0.8rem", font_weight="700", color=MUTED),
                        select_control(
                            [("0", "Any distance")] + [
                                (str(n), rx.cond(State.metric, f"{round(n * 1.609344)} km (driving)", f"{n} mi (driving)"))
                                for n in (25, 50, 100, 200, 300)
                            ],
                            State.radius, State.set_radius, "Search within", id="radius", flex="1",
                        ),
                        width="100%", align="center", gap="12px", margin_top="6px",
                    ),
                    spacing="1", align="start", min_width="0",
                ),
                rx.vstack(
                    rx.grid(
                        date_field("Arrive", "arrive", State.arrive, State.set_arrive),
                        date_field("Leave", "leave", State.leave, State.set_leave),
                        columns="repeat(2, minmax(0, 1fr))", spacing="2", width="100%",
                    ),
                    rx.cond(State.date_warning != "", rx.text(State.date_warning, color="#9B3529", font_size="0.82rem", role="alert")),
                    spacing="2", align="start", min_width="0",
                ),
                columns=rx.breakpoints(initial="1fr", md="1.3fr 1fr"), gap="12px",
                padding="12px", background=CARD, border_radius="14px", box_shadow=SHADOW, width="100%",
            ),
            spacing="4", width="100%", max_width="1200px", margin="0 auto",
        ),
        background=GRADIENT, padding=rx.breakpoints(initial="18px 16px 22px", md="18px 32px 22px"),
    )


def filter_option(label: str, token: str) -> rx.Component:
    return rx.checkbox(
        label, checked=State.active_filters.contains(token),
        on_change=lambda _: State.toggle_filter(token),
        color=INK, size="2", min_height="32px", align_items="center", cursor="pointer",
    )


def filter_group(title: str, options: list[tuple[str, str]]) -> rx.Component:
    return rx.vstack(
        rx.text(title, font_weight="800"),
        *[filter_option(label, token) for label, token in options],
        spacing="1", align="start", width="100%", padding_bottom="14px", border_bottom=f"1px solid {LINE}",
    )


def filter_fields() -> rx.Component:
    return rx.vstack(
        filter_group("Good for your dates", [("Only Good or Great", "good")]),
        filter_group("Type", [(kind, f"type:{kind}") for kind in TYPES]),
        filter_group("Activities", [(activity, f"activity:{activity}") for activity in ACTIVITIES]),
        rx.vstack(
            rx.text("Rating & drive time", font_weight="800"),
            select_control([("0", "Any rating"), ("4.5", "4.5+ stars"), ("4.7", "4.7+ stars")],
                           State.min_rating, State.set_min_rating, "Minimum rating", width="100%"),
            select_control([("0", "Any drive time"), ("1", "Under 1 hour"), ("2", "Under 2 hours"), ("4", "Under 4 hours")],
                           State.max_drive, State.set_max_drive, "Maximum drive time", width="100%"),
            spacing="2", width="100%", align="start", padding_bottom="14px", border_bottom=f"1px solid {LINE}",
        ),
        filter_group("Cost & booking", [("Free", "cost:0"), ("Under $20", "cost:1"), ("$20 or more", "cost:2"),
                                      ("No entry reservation", "no_reservation")]),
        filter_group("Extras", [("Dog friendly", "dogs"), ("Low crowds", "low_crowds")]),
        spacing="4", width="100%", align="start",
    )


def filters() -> rx.Component:
    return rx.el.aside(
        rx.heading("Filters", size="5", margin_bottom="16px"),
        filter_fields(),
        secondary_button("Clear all", on_click=State.clear_filters, width="100%", margin_top="16px"),
        padding="16px", background=CARD, border_radius="14px", box_shadow=SHADOW,
        position="sticky", top="12px", max_height="calc(100vh - 24px)", overflow_y="auto",
        display=rx.breakpoints(initial="none", lg="block"), aria_label="Filters",
    )


def mobile_filters() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.hstack(
                rx.dialog.title("Filters", margin="0"),
                rx.dialog.close(secondary_button(rx.icon("x", size=18), aria_label="Close filters", padding="0 12px")),
                justify="between", align="center", width="100%", margin_bottom="12px",
            ),
            rx.dialog.description("Narrow down your next Utah adventure.", color=MUTED),
            filter_fields(),
            rx.hstack(
                secondary_button("Clear all", on_click=State.clear_filters, flex="1"),
                rx.dialog.close(primary_button("Show results", flex="1")),
                width="100%", spacing="2", position="sticky", bottom="0", background=CARD, padding_top="12px",
            ),
            width="calc(100vw - 24px)", max_width="460px", max_height="90dvh", overflow_y="auto",
            padding="20px", color=INK, background=CARD,
        ),
        open=State.filters_open, on_open_change=State.set_filters_open,
    )


def chip(label, token: str) -> rx.Component:
    active = State.active_filters.contains(token)
    return rx.button(
        label, on_click=State.toggle_filter(token), aria_pressed=active,
        background=rx.cond(active, ACCENT, CARD), color=rx.cond(active, "white", INK),
        border=rx.cond(active, f"1px solid {ACCENT}", f"1px solid {LINE}"),
        border_radius="999px", padding="0 14px", min_height="40px", white_space="nowrap",
        font_weight="600", cursor="pointer", flex_shrink="0",
    )


def badge(label) -> rx.Component:
    return rx.text(
        label, font_size="0.73rem", font_weight="700", background=ACCENT_SOFT,
        color=ACCENT, padding="3px 9px", border_radius="999px",
    )


def favorite_button(place, **props) -> rx.Component:
    saved = State.favorites.contains(place["id"])
    return rx.button(
        rx.icon("heart", size=20, fill=rx.cond(saved, ACCENT, "none")),
        on_click=State.toggle_favorite(place["id"]), aria_pressed=saved,
        aria_label=rx.cond(saved, "Remove " + place["name"] + " from favorites", "Save " + place["name"] + " to favorites"),
        background=rx.cond(saved, ACCENT_SOFT, CARD), color=ACCENT,
        border=f"1px solid {LINE}", min_width="44px", padding="0 10px", **BUTTON, **props,
    )


def compare_button(place, **props) -> rx.Component:
    selected = State.selected_places.contains(place["id"])
    return rx.button(
        rx.cond(selected, "✓ Comparing", "+ Compare"), on_click=State.toggle_place(place["id"]),
        aria_pressed=selected, aria_label=rx.cond(selected, "Remove " + place["name"] + " from comparison", "Compare " + place["name"]),
        background=rx.cond(selected, ACCENT_SOFT, CARD), color=ACCENT,
        border=f"1px solid {ACCENT}", white_space="nowrap", **BUTTON, **props,
    )


def photo_credit(place, **position) -> rx.Component:
    return rx.cond(
        place["image_credit"] != "",
        rx.text("Photo: ", place["image_credit"], position="absolute", color="white", background="rgba(0,0,0,.5)",
                padding="1px 6px", border_radius="6px", font_size="0.65rem", overflow="hidden",
                white_space="nowrap", text_overflow="ellipsis", pointer_events="none", **position),
    )


def place_card(place) -> rx.Component:
    return rx.el.article(
        rx.box(
            rx.el.button(
                rx.image(src=place["image"], alt="", width="100%", height="150px", object_fit="cover"),
                on_click=State.open_details(place["id"]), aria_label="View " + place["name"] + " details",
                width="100%", display="block", padding="0", border="0", cursor="pointer",
            ),
            rx.text(place["kind"], background="rgba(0,0,0,.55)", color="white", border_radius="999px",
                    padding="4px 9px", font_size="0.72rem", font_weight="700", position="absolute", top="10px", left="10px",
                    pointer_events="none"),
            photo_credit(place, left="8px", bottom="6px", max_width="55%"),
            rx.box(
                rx.text(place["score"], color=place["score_color"], font_size="1.35rem", font_weight="800"),
                rx.text(place["score_label"], color=place["score_color"], font_size="0.65rem", font_weight="800"),
                background=CARD, border_radius="12px", box_shadow=SHADOW, padding="6px 10px",
                min_width="64px", text_align="center", position="absolute", right="12px", bottom="-20px",
            ),
            height="150px", position="relative",
        ),
        rx.vstack(
            rx.heading(place["name"], as_="h2", size="4", padding_right="74px", min_height="48px"),
            rx.flex(
                rx.text(place["rating"]), rx.text(place["drive"]), rx.text(place["weather"]),
                rx.text(place["crowds"], " crowds"),
                wrap="wrap", gap="5px 12px", color=MUTED, font_size="0.82rem",
            ),
            rx.flex(*[rx.cond(place[f"tag{i}"] != "", badge(place[f"tag{i}"])) for i in range(4)], wrap="wrap", gap="6px"),
            rx.hstack(
                favorite_button(place),
                primary_button("Details", on_click=State.open_details(place["id"]), flex="1"),
                compare_button(place, flex="1", font_size="0.83rem", padding="0 10px"),
                width="100%", spacing="2", margin_top="auto", padding_top="2px",
            ),
            spacing="3", align="start", padding="12px 14px 14px", flex="1",
        ),
        background=CARD, border_radius="14px", box_shadow=SHADOW, overflow="hidden",
        display="flex", flex_direction="column", min_width="0",
    )


def empty_results() -> rx.Component:
    return rx.vstack(
        rx.icon("search", size=32, color=ACCENT),
        rx.heading(rx.cond(State.active_filters.contains("saved"), "No saved places match yet", "No places match your search"), size="5"),
        rx.text(
            rx.cond(State.active_filters.contains("saved"), "Save a place with its heart button, or adjust your other filters.",
                    "Try a wider distance or fewer filters."),
            color=MUTED, text_align="center",
        ),
        secondary_button("Clear filters", on_click=State.clear_filters),
        align="center", spacing="3", padding="40px 24px", width="100%", background=CARD, border_radius="14px", box_shadow=SHADOW,
    )


def map_view() -> rx.Component:
    return rx.box(
        rx.hstack(rx.heading("Explore Utah", size="5"), small_text("Select a score to see details"), justify="between", wrap="wrap", gap="8px"),
        rx.box(
            rx.el.svg(
                rx.el.polygon(points="0,0 300,0 300,100 501,100 501,500 0,500", fill="#E8E1D0", stroke="#A6B49D", stroke_width="3"),
                view_box="-20 -20 541 540", width="100%", height="100%", aria_hidden=True,
                position="absolute", inset="0",
            ),
            rx.text("UTAH", position="absolute", left="38%", top="49%", font_size="2rem", font_weight="800",
                    letter_spacing=".15em", color=BRAND, opacity=".15", pointer_events="none"),
            rx.foreach(State.results, lambda place: rx.button(
                place["score"], on_click=State.open_details(place["id"]),
                aria_label=place["name"] + ", score " + place["score"] + ". View details",
                title=place["name"], position="absolute", left=place["map_x"], top=place["map_y"],
                transform="translate(-50%, -50%)", border="2px solid white", border_radius="999px",
                background=place["score_color"], color="white", padding="0", min_width="36px", height="36px",
                font_size="0.8rem", font_weight="800", box_shadow=SHADOW, cursor="pointer",
                _hover={"z_index": "2", "scale": "1.15"}, _focus_visible={"z_index": "3"},
            )),
            rx.box(
                width="13px", height="13px", background="#3562AA", border="3px solid white",
                border_radius="50%", box_shadow="0 0 0 3px #3562AA66", title=State.origin_name,
                aria_label="Starting point: " + State.origin_name, role="img", position="absolute",
                left=State.origin_marker["x"], top=State.origin_marker["y"],
                display=State.origin_marker["display"], transform="translate(-50%, -50%)", pointer_events="none",
            ),
            position="relative", aspect_ratio="541 / 540", width="100%", max_width="580px", margin="16px auto",
        ),
        rx.flex(
            *[rx.hstack(rx.box(width="10px", height="10px", border_radius="50%", background=color),
                       small_text(label), spacing="1", align="center") for label, color in [
                           ("Great", "#1E5B2E"), ("Good", "#4D6B2A"), ("Fair", "#7A6A2E"), ("Off-season", "#6B7280")]],
            wrap="wrap", gap="16px", justify="center",
        ),
        small_text("Illustrative map · approximate locations, not navigation.", text_align="center", margin_top="12px"),
        padding="20px", background=CARD, border_radius="14px", box_shadow=SHADOW, width="100%",
    )


def results() -> rx.Component:
    return rx.el.main(
        rx.hstack(
            chip(rx.fragment("Saved (", State.favorites.length(), ")"), "saved"),
            *[chip(label, token) for label, token in [
                ("Hiking", "activity:Hiking"), ("Skiing", "activity:Skiing"), ("Camping", "activity:Camping"),
                ("Low crowds", "low_crowds"),
                ("Water", "activity:Water"), ("Stargazing", "activity:Stargazing"), ("Free", "cost:0"),
            ]],
            spacing="2", overflow_x="auto", width="100%", padding_bottom="4px", role="group", aria_label="Quick filters",
        ),
        rx.flex(
            secondary_button(
                rx.fragment(rx.icon("sliders_horizontal", size=16), "Filters",
                            rx.cond(State.filter_count > 0, rx.text("(", State.filter_count, ")"))),
                on_click=State.set_filters_open(True), display=rx.breakpoints(initial="inline-flex", lg="none"),
            ),
            select_control(
                [("score", "Sort: Best for your dates"), ("drive", "Sort: Closest"),
                 ("rating", "Sort: Top rated"), ("crowds", "Sort: Fewest crowds")],
                State.sort_by, State.set_sort_by, "Sort by", flex="1", min_width="0",
            ),
            rx.link("Compare", href="/compare", color=ACCENT, font_weight="700", font_size="0.88rem",
                    padding="10px 4px", white_space="nowrap", display=rx.breakpoints(initial="none", sm="inline-block")),
            gap="8px", align="center", margin_top="12px",
        ),
        rx.text(State.result_caption, color=MUTED, font_size="0.85rem", margin="12px 0", role="status"),
        rx.cond(
            State.date_warning != "",
            rx.box(rx.text(State.date_warning, color="#9B3529"), padding="24px", background=CARD, border_radius="14px"),
            rx.cond(
                State.results.length() == 0, empty_results(),
                rx.cond(State.show_map, map_view(),
                        rx.grid(rx.foreach(State.results, place_card),
                                columns="repeat(auto-fill, minmax(min(100%, 300px), 1fr))", gap="16px", width="100%")),
            ),
        ),
        small_text("Places from the National Park Service, Recreation.gov and OpenStreetMap, plus curated samples. "
                   "Seasonal scores, drive times and crowds are estimates; curated ratings and reviews are sample data.",
                   margin_top="20px"),
        width="100%", min_width="0",
    )


def detail_section(title: str, *children) -> rx.Component:
    return rx.vstack(rx.heading(title, as_="h3", size="4"), *children, spacing="2", align="start", width="100%")


def text_list(items, checklist=False) -> rx.Component:
    return rx.el.ul(
        rx.foreach(items, lambda item: rx.el.li(
            rx.fragment("☐  ", item) if checklist else item, margin_bottom="6px",
        )),
        padding_left="0" if checklist else "20px", list_style_type="none" if checklist else "disc",
        font_size="0.9rem", width="100%",
    )


def detail_dialog() -> rx.Component:
    p = State.detail
    return rx.dialog.root(
        rx.dialog.content(
            rx.hstack(
                rx.dialog.title(p["name"], margin="0", font_size="1.15rem"),
                rx.hstack(
                    favorite_button(p),
                    rx.dialog.close(secondary_button(rx.icon("x", size=20), aria_label="Close details", padding="0 12px")),
                    spacing="2", flex_shrink="0",
                ),
                justify="between", align="center", width="100%", padding="12px 16px",
                position="sticky", top="0", background=CARD, z_index="2", border_bottom=f"1px solid {LINE}",
            ),
            rx.box(
                rx.image(src=p["image"], alt="", width="100%", height="140px", object_fit="cover"),
                rx.text(p["kind"], position="absolute", top="10px", left="16px", color="white",
                        background="rgba(0,0,0,.55)", border_radius="999px", padding="4px 9px", font_size="0.75rem", font_weight="700"),
                photo_credit(p, right="10px", bottom="8px", max_width="60%"),
                position="relative",
            ),
            rx.vstack(
                rx.dialog.description(p["description"], color=INK, font_size="0.95rem", margin="0"),
                rx.hstack(
                    rx.cond(p["url"] != "", rx.link("Official site ↗", href=p["url"], is_external=True,
                                                    color=ACCENT, font_weight="700", font_size="0.9rem")),
                    rx.cond(p["maps_url"] != "", rx.link("View on Google Maps ↗", href=p["maps_url"], is_external=True,
                                                         color=ACCENT, font_weight="700", font_size="0.9rem")),
                    spacing="4", wrap="wrap",
                ),
                rx.cond(p["estimate_note"] != "", small_text(p["estimate_note"])),
                rx.box(
                    rx.text(p["score_text"], " for ", State.trip_label, font_weight="800", color=BRAND),
                    rx.text(p["weather_kind"], " around ", p["weather"], "; ", p["crowds"], " crowds. Best months: ", p["best"], ".",
                            font_size="0.9rem", margin_top="4px"),
                    rx.cond(p["now"] != "", rx.text("Right now: ", p["now"], font_size="0.85rem", margin_top="4px", color=MUTED)),
                    padding="12px 14px", background=ACCENT_SOFT, border_radius="10px", width="100%",
                ),
                rx.cond(State.detail_forecast.length() > 0, detail_section(
                    "Forecast for your trip",
                    rx.grid(
                        rx.foreach(State.detail_forecast, lambda day: rx.vstack(
                            small_text(day["day"], font_weight="700"),
                            rx.text(day["temps"], font_size="0.9rem", font_weight="700"),
                            small_text(day["text"]),
                            rx.cond(day["rain"] != "", small_text(day["rain"])),
                            spacing="0", align="start", padding="8px 10px", background=BG, border_radius="8px",
                        )),
                        columns="repeat(auto-fill, minmax(110px, 1fr))", gap="8px", width="100%",
                    ),
                    small_text("Forecast from Open-Meteo, refreshed hourly."),
                )),
                rx.grid(
                    rx.foreach(State.detail_facts, lambda fact: rx.vstack(
                        small_text(fact["label"], font_weight="700"),
                        rx.text(fact["value"], font_size="0.9rem", font_weight="600"),
                        spacing="1", align="start",
                    )),
                    columns="repeat(2, minmax(0, 1fr))", gap="14px", width="100%",
                ),
                rx.cond(p["peak"] == "yes", rx.box(
                    rx.text("Peak season for your dates", font_weight="800"),
                    rx.text("Arrive early, or try: ", p["quiet_time"], font_size="0.9rem", margin_top="4px"),
                    background="#EDE3CF", color="#5B4A2A", padding="12px 14px", border_radius="10px", width="100%",
                )),
                detail_section(
                    "When to go",
                    rx.grid(
                        rx.foreach(State.detail_months, lambda month: rx.vstack(
                            rx.box(height=month["height"], width="70%", border_radius="4px 4px 0 0", background=month["color"]),
                            rx.text(month["dots"], font_size="0.75rem", line_height="1", color="#6B4F2A"),
                            rx.text(month["short"], font_size="0.72rem", font_weight="700", color=MUTED),
                            height="96px", padding="4px 0", align="center", justify="end", spacing="1",
                            border_radius="6px", background=month["background"], outline=month["outline"],
                            title=month["description"], aria_label=month["description"], role="img",
                        )),
                        columns="repeat(12, minmax(0, 1fr))", gap="3px", width="100%",
                    ),
                    small_text("Bars = seasonal match · Brown dots = crowds · Outlined = your trip."),
                    small_text("Busiest: " + p["busy"] + "."),
                ),
                rx.cond(
                    (State.detail_things.length() > 0) | (State.detail_activities.length() > 0),
                    detail_section("Things to do", text_list(State.detail_things),
                                   rx.flex(rx.foreach(State.detail_activities, badge), wrap="wrap", gap="6px")),
                ),
                detail_section("What to expect", text_list(State.detail_expectations)),
                detail_section("Packing list for your dates", text_list(State.detail_packing, checklist=True)),
                detail_section("For a quieter visit", rx.text(p["quiet_time"], font_size="0.9rem")),
                detail_section("First time in Utah?", rx.text(p["tip"], font_size="0.9rem")),
                rx.cond(State.detail_reviews.length() > 0, detail_section(
                    "Reviews", small_text(p["review_source"]),
                    rx.foreach(State.detail_reviews, lambda review: rx.box(
                        rx.text(review["stars"], color="#7A6A2E", letter_spacing="1px", aria_label=review["label"]),
                        rx.text("“", review["text"], "”", font_size="0.9rem", margin="4px 0"),
                        small_text(review["who"]), background=BG, padding="10px 12px", border_radius="10px", width="100%",
                    )),
                )),
                compare_button(p, width="100%"),
                spacing="5", align="start", padding="18px", width="100%",
            ),
            padding="0", width="calc(100vw - 24px)", max_width="640px", max_height="92dvh",
            overflow_y="auto", border_radius="18px", color=INK, background=CARD,
        ),
        open=State.detail_open, on_open_change=State.set_detail_open,
    )


def compare_tray() -> rx.Component:
    return rx.cond(
        State.selected_places.length() > 0,
        rx.box(
            rx.vstack(
                rx.text(State.selected_places.length(), " selected", font_weight="800", font_size="0.8rem", white_space="nowrap"),
                rx.text(State.selected_names, font_size="0.72rem", opacity=".8", overflow="hidden",
                        text_overflow="ellipsis", white_space="nowrap", max_width="190px",
                        display=rx.breakpoints(initial="none", sm="block")),
                spacing="0", align="start", min_width="0",
            ),
            rx.button("Clear", on_click=State.clear_comparison, background="transparent", color="white",
                      min_height="36px", padding="0 8px", font_size="0.8rem", cursor="pointer"),
            rx.link("Compare", href="/compare", background=CARD, color=INK, border_radius="7px",
                    padding="8px 11px", font_size="0.8rem", font_weight="800", white_space="nowrap"),
            position="fixed", display="flex", align_items="center", gap="8px", left="50%", bottom="12px",
            transform="translateX(-50%)", width="max-content", max_width="calc(100vw - 32px)",
            background=INK, color="white", border_radius="12px", padding="7px 9px",
            box_shadow="0 4px 14px rgba(0,0,0,.2)", z_index="5", role="region", aria_label="Selected places for comparison",
        ),
    )


def comparison_table() -> rx.Component:
    return rx.box(
        rx.el.table(
            rx.el.thead(rx.el.tr(
                rx.el.th("At a glance", scope="col", text_align="left", padding="16px", min_width="150px", color=MUTED),
                rx.foreach(State.comparison, lambda place: rx.el.th(
                    rx.image(src=place["image"], alt="", height="90px", width="100%", object_fit="cover", border_radius="8px", margin_bottom="10px"),
                    rx.el.button(place["name"], on_click=State.open_details(place["id"]), color=BRAND,
                                 font_weight="800", font_size="1rem", text_align="left", cursor="pointer"),
                    rx.button("Remove", on_click=State.toggle_place(place["id"]), aria_label="Remove " + place["name"] + " from comparison",
                              variant="ghost", color=MUTED, margin_top="8px", display="block", cursor="pointer"),
                    scope="col", min_width="220px", max_width="300px", text_align="left", vertical_align="top", padding="16px",
                )),
            )),
            rx.el.tbody(*[
                rx.el.tr(
                    rx.el.th(label, scope="row", text_align="left", padding="12px 16px", font_size="0.85rem", font_weight="700",
                             vertical_align="top", border_top=f"1px solid {LINE}", background="#FAF8F2"),
                    rx.foreach(State.comparison, lambda place: rx.el.td(
                        rx.cond(place[key + "_best"] == "yes", rx.text.span("✓ ", font_weight="800", aria_label="Best value")),
                        place[key], padding="12px 16px", font_size="0.88rem", vertical_align="top", border_top=f"1px solid {LINE}",
                        background=rx.cond(place[key + "_best"] == "yes", ACCENT_SOFT, CARD),
                        color=rx.cond(place[key + "_best"] == "yes", BRAND, INK),
                    )),
                )
                for label, key in COMPARISON_ROWS
            ]),
            width="100%", border_collapse="collapse",
        ),
        overflow_x="auto", width="100%", background=CARD, border_radius="14px", box_shadow=SHADOW,
        tab_index=0, role="region", aria_label="Destination comparison, scroll horizontally for more columns",
    )


def compare_page() -> rx.Component:
    return rx.box(
        rx.el.header(
            rx.flex(rx.link(brand(), href="/", text_decoration="none"), units(),
                    align="center", justify="between", wrap="wrap", gap="14px", max_width="1200px", margin="0 auto"),
            padding="18px 24px", background=GRADIENT,
        ),
        rx.el.main(
            rx.link("← Back to results", href="/", color=ACCENT, font_weight="700"),
            rx.heading("Compare your Utah options", size=rx.breakpoints(initial="6", sm="8"), margin_top="18px"),
            rx.text(State.trip_label, " · From ", State.origin_name, color=MUTED, margin="8px 0 24px"),
            rx.cond(
                State.date_warning != "",
                rx.box(rx.text(State.date_warning), rx.link("Update trip dates", href="/", color=ACCENT), padding="24px", background=CARD),
                rx.cond(
                    State.selected_places.length() > 0,
                    rx.vstack(
                        comparison_table(),
                        small_text("✓ highlights the best value in a row. Sample data; drive estimates are approximate."),
                        rx.flex(
                            rx.link("← Keep exploring", href="/", color=ACCENT, font_weight="700", padding="12px 0"),
                            secondary_button("Clear comparison", on_click=State.clear_comparison),
                            width="100%", justify="between", gap="16px", wrap="wrap",
                        ),
                        spacing="4", align="start", width="100%",
                    ),
                    rx.vstack(
                        rx.heading("No places selected yet", size="5"),
                        rx.text("Use + Compare on the places you want to evaluate.", color=MUTED),
                        rx.link("Browse places →", href="/", color=ACCENT, font_weight="700"),
                        spacing="3", align="start", background=CARD, padding="28px", border_radius="14px", box_shadow=SHADOW,
                    ),
                ),
            ),
            max_width="1200px", margin="0 auto", padding="28px 16px 64px",
        ),
        detail_dialog(), min_height="100vh", background=BG, color=INK,
        on_mount=set_color_mode("light"),
    )


def index() -> rx.Component:
    return rx.box(
        header(),
        rx.grid(
            filters(), results(),
            columns=rx.breakpoints(initial="minmax(0, 1fr)", lg="280px minmax(0, 1fr)"),
            align_items="start", gap="24px", max_width="1200px", margin="16px auto 0",
            padding="0 16px 120px", width="100%",
        ),
        rx.button(
            rx.cond(State.show_map, "List", "Map"), on_click=State.toggle_view,
            aria_label=rx.cond(State.show_map, "Switch to list view", "Switch to map view"),
            aria_pressed=State.show_map, position="fixed", right="16px",
            bottom=rx.cond(State.selected_places.length() > 0, "84px", "20px"),
            background=ACCENT, color="white", border="0", border_radius="999px",
            min_height="48px", padding="0 18px", font_weight="800", cursor="pointer",
            box_shadow="0 4px 14px rgba(0,0,0,.2)", z_index="4",
        ),
        compare_tray(), mobile_filters(), detail_dialog(),
        min_height="100vh", background=BG, color=INK,
        on_mount=set_color_mode("light"),
    )


app = rx.App(
    style={
        "font_family": 'system-ui, -apple-system, "Segoe UI", sans-serif',
        "color": INK,
        "::selection": {"background": ACCENT_SOFT},
        "button:focus-visible, a:focus-visible, select:focus-visible, input:focus-visible": {
            "outline": f"3px solid {ACCENT}", "outline_offset": "3px",
        },
    },
)
# This design is intentionally light, including when an older local session
# saved a dark/system theme before the mockup was ported.
ON_LOAD = [State.refresh_weather, State.load_drives, State.prefetch_google]
app.add_page(index, title="Utah Wayfinder", on_load=ON_LOAD)
app.add_page(compare_page, route="/compare", title="Compare Utah destinations", on_load=ON_LOAD)
