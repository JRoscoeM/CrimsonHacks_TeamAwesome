"""Utah Wayfinder's Reflex UI scaffold.

This module uses local placeholder content only. It mirrors the visual mockup
without reading from, embedding, or otherwise depending on ``index.html``.
"""

import reflex as rx


BG, INK, MUTED, LINE = "#F5F0E6", "#1F2A1F", "#56604F", "#DDD5C4"
BRAND, ACCENT, ACCENT_SOFT, CARD = "#2F5233", "#3B6E4A", "#E4EEDF", "#FFFFFF"
SHADOW = "0 1px 3px rgba(0, 0, 0, .08), 0 4px 14px rgba(0, 0, 0, .06)"


class State(rx.State):
    """UI-only state; real search and API data will be connected later."""

    metric: bool = False
    show_map: bool = False

    def toggle_units(self):
        self.metric = not self.metric

    def toggle_view(self):
        self.show_map = not self.show_map


def pill(label: str, active: bool = False) -> rx.Component:
    return rx.button(
        label,
        background=ACCENT if active else CARD,
        color="white" if active else INK,
        border=f"1px solid {ACCENT if active else LINE}",
        border_radius="999px", padding="0 14px", min_height="40px",
        font_weight="600", white_space="nowrap",
    )


def field(label: str, placeholder: str, value: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, font_size="0.8rem", font_weight="700", color=MUTED),
        rx.input(placeholder=placeholder, default_value=value, width="100%", height="44px",
                 border=f"1px solid {LINE}", border_radius="10px", background="white"),
        spacing="1", width="100%",
    )


def header() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.hstack(
                    rx.box("✦", font_size="1.6rem", line_height="1"),
                    rx.vstack(rx.heading("Utah Wayfinder", size="5", color="white"),
                              rx.text("From powder to sandstone", color="rgba(255,255,255,.9)", font_size="0.85rem"),
                              spacing="0", align="start"),
                    spacing="3", align="center"),
                rx.hstack(
                    rx.button("°F · mi", on_click=State.toggle_units,
                              background=rx.cond(State.metric, "transparent", "white"),
                              color=rx.cond(State.metric, "white", BRAND), border="0", border_radius="999px",
                              min_height="38px", font_weight="700"),
                    rx.button("°C · km", on_click=State.toggle_units,
                              background=rx.cond(State.metric, "white", "transparent"),
                              color=rx.cond(State.metric, BRAND, "white"), border="0", border_radius="999px",
                              min_height="38px", font_weight="700"),
                    spacing="0", padding="3px", background="rgba(255,255,255,.18)", border_radius="999px"),
                width="100%", justify="between", align="center"),
            rx.box(
                rx.grid(
                    rx.vstack(
                        rx.text("Starting from", font_size="0.8rem", font_weight="700", color=MUTED),
                        rx.hstack(rx.input(default_value="Salt Lake City, UT", width="100%", height="44px",
                                            border=f"1px solid {LINE}", border_radius="10px"),
                                  rx.button("📍 Near me", background=ACCENT_SOFT, color=ACCENT,
                                            border=f"1px solid {ACCENT}", border_radius="10px", min_height="44px",
                                            font_weight="700", white_space="nowrap"), width="100%"),
                        rx.text('Using Salt Lake City. Tap "Near me" to use your current location.',
                                font_size="0.78rem", color=MUTED), spacing="1", align="start"),
                    rx.vstack(
                        rx.hstack(field("Arrive", "mm/dd/yyyy"), field("Leave", "mm/dd/yyyy"), width="100%", spacing="2"),
                        rx.hstack(rx.text("Try:", font_size="0.85rem", color=MUTED), pill("🌸 Spring break"),
                                  pill("☀️ Summer"), pill("❄️ Ski week"), spacing="2", wrap="wrap", width="100%"),
                        spacing="3", align="start"),
                    columns="repeat(auto-fit, minmax(290px, 1fr))", spacing="5", width="100%"),
                background="white", color=INK, border_radius="14px", padding="12px", box_shadow=SHADOW, width="100%"),
            spacing="4", width="100%", max_width="1200px", margin="0 auto"),
        background="linear-gradient(135deg, #1F3B24, #2F5233 55%, #4A6B45)",
        padding="18px 32px 22px", width="100%")


def filter_group(title: str, options: list[str]) -> rx.Component:
    return rx.vstack(
        rx.text(title, font_weight="800", color=INK),
        *[rx.hstack(rx.checkbox(), rx.text(option, font_size="0.92rem"), spacing="2", min_height="32px", align="center") for option in options],
        spacing="1", align="start", width="100%", padding_bottom="12px", border_bottom=f"1px solid {LINE}")


def filters() -> rx.Component:
    return rx.box(
        rx.vstack(rx.heading("Filters", size="5", color=INK),
                  filter_group("Good for your dates", ["Only Good or Great for my dates"]),
                  filter_group("Type", ["National Park", "State Park", "Ski Resort", "Campground"]),
                  filter_group("Activities", ["Hiking", "Camping", "Skiing", "Scenic Drive"]),
                  filter_group("♿ Accessibility", ["Wheelchair friendly", "Stroller friendly", "Restrooms"]),
                  filter_group("Extras", ["Family friendly", "Dog friendly", "Low crowds"]),
                  rx.hstack(rx.button("Clear all", variant="outline", flex="1"),
                            rx.button("Show results", background=ACCENT, color="white", flex="1"), width="100%"),
                  spacing="4", align="start", width="100%"),
        background=CARD, border_radius="14px", box_shadow=SHADOW, padding="16px", width="100%")


def badge(label: str) -> rx.Component:
    return rx.text(label, font_size="0.75rem", font_weight="700", background=ACCENT_SOFT, color=ACCENT,
                   padding="3px 9px", border_radius="999px")


def place_card(name: str, kind: str, score: str, rating: str, drive: str, weather: str,
               gradient: str, tags: list[str]) -> rx.Component:
    return rx.box(
        rx.box(
            rx.text(kind, background="rgba(0,0,0,.55)", color="white", border_radius="999px", padding="4px 9px",
                    font_size="0.72rem", font_weight="700", position="absolute", top="10px", left="10px"),
            rx.box(rx.text(score, color="#1E5B2E", font_size="1.35rem", font_weight="800"),
                   rx.text("MATCH", font_size="0.65rem", font_weight="800", color=MUTED), background="white",
                   border_radius="12px", box_shadow=SHADOW, padding="6px 10px", text_align="center",
                   position="absolute", right="12px", bottom="-20px"),
            height="150px", background=gradient, position="relative"),
        rx.vstack(
            rx.heading(name, size="4", color=INK, padding_right="72px"),
            rx.flex(rx.text(f"⭐ {rating}"), rx.text(f"🚗 {drive}"), rx.text(f"🌡️ {weather}"),
                    rx.text("👥 Moderate crowds"), wrap="wrap", gap="4px 12px", color=MUTED, font_size="0.85rem", width="100%"),
            rx.hstack(*[badge(tag) for tag in tags], wrap="wrap", spacing="2", width="100%"),
            rx.hstack(rx.button("Details", background=BRAND, color="white", border="0", flex="1"),
                      rx.button("+ Compare", variant="outline", flex="1"), width="100%"),
            spacing="3", align="start", width="100%", padding="12px 14px 14px"),
        background=CARD, border_radius="14px", box_shadow=SHADOW, overflow="hidden", width="100%")


def results() -> rx.Component:
    return rx.vstack(
        rx.hstack(pill("Parks", True), pill("Skiing"), pill("Camping"), pill("Family friendly"), pill("Low crowds"),
                  spacing="2", overflow_x="auto", width="100%"),
        rx.hstack(rx.button("⚙︎ Filters", variant="outline", display=["inline-flex", "none"]),
                  rx.box("Sort: Best for your dates ▾", border=f"1px solid {LINE}", border_radius="10px",
                         padding="11px 12px", background="white", flex="1", color=INK), width="100%"),
        rx.text("24 places for Jun 13–16, from Salt Lake City", color=MUTED, font_size="0.9rem"),
        rx.grid(
            place_card("Zion National Park", "NATIONAL PARK", "94", "4.9 (48,210)", "4 hr 18 min", "86°F",
                       "linear-gradient(135deg, #d88b5f, #f0c77c 55%, #55704b)", ["Hiking", "Camping", "Family friendly"]),
            place_card("Snow Canyon State Park", "STATE PARK", "89", "4.7 (6,120)", "4 hr 4 min", "88°F",
                       "linear-gradient(135deg, #c3613d, #e7a56e 55%, #9dba78)", ["Hiking", "Dog friendly", "Low crowds"]),
            place_card("Canyonlands", "NATIONAL PARK", "87", "4.8 (18,760)", "3 hr 47 min", "82°F",
                       "linear-gradient(135deg, #8c533d, #d8a26a 52%, #5c7850)", ["Scenic drive", "Stargazing", "Camping"]),
            columns="repeat(auto-fill, minmax(290px, 1fr))", spacing="4", width="100%"),
        spacing="4", align="start", width="100%")


def map_placeholder() -> rx.Component:
    return rx.box(
        rx.vstack(rx.heading("Utah map", size="6", color=BRAND),
                  rx.text("Map integration placeholder — pins will be supplied by future search data.", color=MUTED),
                  rx.box(rx.text("UTAH", color=BRAND, font_size="2rem", font_weight="800", opacity=".55"),
                         rx.text("94", background="#1E5B2E", color="white", border_radius="999px", padding="10px", position="absolute", top="26%", left="31%"),
                         rx.text("89", background="#4D6B2A", color="white", border_radius="999px", padding="10px", position="absolute", top="62%", left="22%"),
                         rx.text("87", background="#4D6B2A", color="white", border_radius="999px", padding="10px", position="absolute", top="48%", right="23%"),
                         height="420px", width="100%", position="relative", background="#EFE8DA", border="3px solid #4A6B45",
                         border_radius="8px", display="flex", align_items="end", padding="24px"),
                  spacing="3", align="start"),
        background="white", border_radius="14px", box_shadow=SHADOW, padding="16px", width="100%")


def index() -> rx.Component:
    return rx.box(
        header(),
        rx.grid(rx.box(filters(), display=["none", "none", "block"]), rx.cond(State.show_map, map_placeholder(), results()),
                columns=rx.breakpoints(initial="1fr", lg="280px minmax(0, 1fr)"), spacing="6", max_width="1200px", margin="16px auto 0",
                padding="0 16px 116px", width="100%"),
        rx.button(rx.cond(State.show_map, "☰ List", "🗺️ Map"), on_click=State.toggle_view, position="fixed", right="16px",
                  bottom="20px", background=ACCENT, color="white", border="0", border_radius="999px", min_height="48px",
                  padding="0 18px", font_weight="800", box_shadow="0 4px 14px rgba(0,0,0,.2)"),
        rx.box(rx.text("Compare tray", font_weight="800"), rx.text("Select places to compare", font_size="0.85rem", opacity=".85", flex="1"),
               rx.button("Compare", background="white", color=INK, border="0"), position="fixed", display=["none", "flex"],
               align_items="center", gap="10px", left="12px", right="84px", bottom="12px", background=INK, color="white",
               border_radius="14px", padding="10px 12px", box_shadow="0 6px 24px rgba(0,0,0,.25)"),
        min_height="100vh", background=BG, color=INK, font_family='system-ui, -apple-system, "Segoe UI", sans-serif')


app = rx.App()
app.add_page(index, title="Utah Wayfinder")
